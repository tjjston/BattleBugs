from datetime import datetime, timezone, timedelta
from typing import Optional
import random as _random

from flask import current_app
from sqlalchemy import func

from app import db
from app.models import Bug, Job


VISUAL_LORE_JOB = 'visual_lore_enrichment'
TAXONOMY_JOB = 'taxonomy_enrichment'
STAT_RECALC_JOB = 'stat_recalculation'
SEASONAL_TOURNAMENT_JOB = 'create_seasonal_tournaments'

MAX_JOB_ATTEMPTS = 3


def enqueue_job(job_type: str, payload: dict) -> Job:
    job = Job(type=job_type, status='queued')
    job.payload = payload
    db.session.add(job)
    db.session.commit()
    return job


def enqueue_bug_enrichment(bug: Bug, image_path: Optional[str] = None) -> list[Job]:
    bug.enrichment_status = 'pending'
    bug.enrichment_error = None
    db.session.add(bug)
    db.session.flush()

    jobs = [
        Job(type=VISUAL_LORE_JOB, status='queued'),
        Job(type=TAXONOMY_JOB, status='queued'),
    ]
    for job in jobs:
        job.payload = {'bug_id': bug.id, 'image_path': image_path or bug.image_path}
        db.session.add(job)

    db.session.commit()
    return jobs


def process_next_job() -> Optional[Job]:
    job = Job.query.filter_by(status='queued').order_by(Job.created_at.asc()).first()
    if not job:
        return None
    return process_job(job)


def process_job(job: Job) -> Job:
    job.status = 'processing'
    job.started_at = datetime.now(timezone.utc)
    job.attempts = (job.attempts or 0) + 1
    job.error = None
    db.session.commit()

    try:
        result = _dispatch_job(job)
        job.result = result or {}
        job.status = 'complete'
        job.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        current_app.logger.exception("Background job %s failed", job.id)
        job.status = 'dead' if job.attempts >= MAX_JOB_ATTEMPTS else 'failed'
        job.error = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        _mark_bug_enrichment_failed(job, str(exc))

    db.session.commit()
    _refresh_bug_enrichment_status(job)
    return job


def retry_job(job_id: int) -> Job:
    job = db.get_or_404(Job, job_id)
    job.status = 'queued'
    job.error = None
    job.attempts = 0
    job.started_at = None
    job.completed_at = None
    db.session.commit()
    return job


def enqueue_seasonal_tournaments() -> Job:
    """Queue a job that creates per-tier tournaments for the current season if none exist."""
    return enqueue_job(SEASONAL_TOURNAMENT_JOB, {})


def _dispatch_job(job: Job) -> dict:
    if job.type == VISUAL_LORE_JOB:
        return _run_visual_lore_job(job)
    if job.type == TAXONOMY_JOB:
        return _run_taxonomy_job(job)
    if job.type == STAT_RECALC_JOB:
        return _run_stat_recalculation_job(job)
    if job.type == SEASONAL_TOURNAMENT_JOB:
        return _run_seasonal_tournaments_job(job)
    raise ValueError(f'Unknown job type: {job.type}')


def _bug_from_job(job: Job) -> Bug:
    bug_id = job.payload.get('bug_id')
    if not bug_id:
        raise ValueError('Job payload missing bug_id')
    return db.get_or_404(Bug, bug_id)


def _run_visual_lore_job(job: Job) -> dict:
    import os as _os
    bug = _bug_from_job(job)
    image_path = job.payload.get('image_path') or bug.image_path
    if not image_path.startswith('/'):
        image_path = f"{current_app.config['UPLOAD_FOLDER']}/{image_path}"

    current_app.logger.info(
        "JOB visual_lore #%s — bug#%s image_path=%s exists=%s",
        job.id, bug.id, image_path, _os.path.exists(image_path),
    )
    if not _os.path.exists(image_path):
        upload_dir = current_app.config['UPLOAD_FOLDER']
        on_disk = _os.listdir(upload_dir) if _os.path.isdir(upload_dir) else []
        current_app.logger.error(
            "JOB visual_lore #%s — image missing at %s. "
            "UPLOAD_FOLDER=%s. Files matching bug#%s owner: %s",
            job.id, image_path, upload_dir,
            bug.id,
            [f for f in on_disk if f.startswith(f"{bug.user_id}_")],
        )
        raise FileNotFoundError(f"Bug image not found: {image_path}")

    bug.enrichment_status = 'processing'
    db.session.add(bug)
    db.session.commit()

    from app.services.visual_lore_generator import VisualLoreAnalyzer

    analyzer = VisualLoreAnalyzer()
    analyzer.apply_visual_lore_to_bug(bug, image_path)
    return {'bug_id': bug.id, 'visual_lore': 'complete'}


def _run_taxonomy_job(job: Job) -> dict:
    bug = _bug_from_job(job)
    if not bug.scientific_name:
        return {'bug_id': bug.id, 'taxonomy': 'skipped'}

    from app.services.taxonomy import TaxonomyService

    taxonomy = TaxonomyService()
    species = taxonomy.get_species_details(scientific_name=bug.scientific_name)
    if species:
        bug.species_id = species.id
        bug.common_name = bug.common_name or species.common_name
        bug.scientific_name = bug.scientific_name or species.scientific_name
        db.session.add(bug)
        db.session.commit()
        return {'bug_id': bug.id, 'taxonomy': 'linked', 'species_id': species.id}
    return {'bug_id': bug.id, 'taxonomy': 'not_found'}


def _run_stat_recalculation_job(job: Job) -> dict:
    bug = _bug_from_job(job)
    from app.services.tier_system import LLMStatGenerator, TierSystem

    generator = LLMStatGenerator()
    stats = generator.generate_stats_with_llm({
        'scientific_name': bug.scientific_name,
        'common_name': bug.common_name,
        'size_mm': bug.species_info.average_size_mm if bug.species_info else None,
        'traits': [],
        'species_info': bug.species_info.to_dict() if bug.species_info else None,
    })
    bug.attack = stats['attack']
    bug.defense = stats['defense']
    bug.speed = stats['speed']
    bug.special_ability = stats.get('special_ability')
    bug.stats_generation_method = 'llm_recalc_job'
    bug.stats_generated = True
    bug.tier = TierSystem.assign_tier(bug)
    db.session.add(bug)
    db.session.commit()
    return {'bug_id': bug.id, 'stats': stats}


def _mark_bug_enrichment_failed(job: Job, error: str) -> None:
    bug_id = job.payload.get('bug_id')
    if not bug_id:
        return
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return
    bug.enrichment_status = 'failed'
    bug.enrichment_error = error
    db.session.add(bug)


def _refresh_bug_enrichment_status(job: Job) -> None:
    bug_id = job.payload.get('bug_id')
    if not bug_id:
        return
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return

    related = Job.query.filter(
        func.json_extract(Job.payload_json, '$.bug_id') == bug_id
    ).all()
    if any(j.status == 'failed' for j in related):
        bug.enrichment_status = 'failed'
        bug.enrichment_error = next((j.error for j in related if j.status == 'failed'), None)
    elif related and all(j.status == 'complete' for j in related):
        bug.enrichment_status = 'complete'
        bug.enrichment_error = None
    elif any(j.status == 'processing' for j in related):
        bug.enrichment_status = 'processing'
    else:
        bug.enrichment_status = 'pending'
    db.session.add(bug)
    db.session.commit()


def _run_seasonal_tournaments_job(_job: Job) -> dict:
    """Create one tournament per tier for the current season, if not already present.

    Creates up to 6 tournaments (uber/ou/uu/ru/nu/zu), each:
    - single_elimination format
    - max 64 participants, 2 per user
    - starts 1 week from now, deadline 6 days from now
    """
    from datetime import timedelta
    from app.models import Tournament
    from app.services.seasonal_tournament import get_season_key_for_date
    from app.services.news_service import get_current_season

    now = datetime.now(timezone.utc)
    try:
        season_key = get_season_key_for_date(now)
    except Exception:
        season = get_current_season()
        season_key = getattr(season, 'key', now.strftime('%Y_Q%q'))

    tiers = ['uber', 'ou', 'uu', 'ru', 'nu', 'zu']
    created = []
    for tier in tiers:
        exists = Tournament.query.filter_by(season_key=season_key, tier=tier).first()
        if exists:
            continue
        t = Tournament(
            name=f'{season_key.replace("_", " ").title()} — {tier.upper()} Cup',
            start_date=now + timedelta(days=7),
            registration_deadline=now + timedelta(days=6),
            status='registration',
            tier=tier,
            season_key=season_key,
            format='single_elimination',
            max_participants=64,
            submissions_per_user=2,
        )
        db.session.add(t)
        created.append(tier)

    db.session.commit()
    current_app.logger.info("Seasonal tournaments created for %s: %s", season_key, created or ['(none — all existed)'])
    return {'season_key': season_key, 'created': created}


def start_scheduler(app) -> None:
    if not app.config.get('ENABLE_BACKGROUND_JOBS', True):
        return
    if getattr(app, '_battlebugs_scheduler_started', False):
        return

    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)

    def tick():
        with app.app_context():
            process_next_job()

    def daily_maintenance():
        with app.app_context():
            try:
                from app.services.seasonal_tournament import ensure_seasonal_tournament
                t = ensure_seasonal_tournament()
                if t:
                    current_app.logger.info("Seasonal tournament created: %s", t.name)
            except Exception:
                current_app.logger.exception("daily_maintenance: seasonal tournament check failed")

    scheduler.add_job(
        tick,
        'interval',
        seconds=app.config.get('JOB_POLL_INTERVAL_SECONDS', 15),
        id='battlebugs_job_worker',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        daily_maintenance,
        'interval',
        hours=24,
        id='battlebugs_daily_maintenance',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    def season_tick():
        with app.app_context():
            try:
                advance_season_phases()
                play_due_season_matches()
            except Exception:
                current_app.logger.exception("season_tick failed")

    scheduler.add_job(
        season_tick,
        'interval',
        minutes=30,
        id='battlebugs_season_tick',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
    )

    def quarterly_season_creation():
        """Create the full seasonal cohort (one Season per tier) at the start of each season."""
        with app.app_context():
            try:
                from app.services.seasonal_tournament import auto_create_seasonal_cohort
                created = auto_create_seasonal_cohort()
                if created:
                    current_app.logger.info(
                        "quarterly_season_creation: created %d seasons: %s",
                        len(created), [s.season_key for s in created],
                    )
            except Exception:
                current_app.logger.exception("quarterly_season_creation failed")

    from apscheduler.triggers.cron import CronTrigger
    scheduler.add_job(
        quarterly_season_creation,
        CronTrigger(month='3,6,9,12', day='1', hour='0', minute='5'),
        id='battlebugs_quarterly_seasons',
        replace_existing=True,
        max_instances=1,
    )

    def weekly_ranking_recalc():
        """Recalculate MMA contender rankings across all tiers."""
        with app.app_context():
            try:
                from app.services.championship_service import recalculate_all_rankings, expire_stale_callouts
                recalculate_all_rankings()
                expire_stale_callouts()
                current_app.logger.info("weekly_ranking_recalc: complete")
            except Exception:
                current_app.logger.exception("weekly_ranking_recalc failed")

    scheduler.add_job(
        weekly_ranking_recalc,
        CronTrigger(day_of_week='mon', hour='3', minute='0'),
        id='battlebugs_weekly_ranking_recalc',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    def bimonthly_title_fight_check():
        """Schedule title fights for belts that don't yet have one, and lock expired bidding windows."""
        with app.app_context():
            try:
                from app.services.championship_service import (
                    ensure_championships, schedule_title_fights,
                )
                from app.models import TitleFight
                from datetime import datetime, timezone as _tz
                ensure_championships()
                schedule_title_fights()
                # Close any bidding windows that have expired
                now = datetime.now(_tz.utc)
                open_fights = TitleFight.query.filter_by(status='bidding').all()
                for fight in open_fights:
                    if fight.bid_closes_at and fight.bid_closes_at <= now:
                        from app.services.championship_service import close_bidding
                        try:
                            close_bidding(fight.id)
                        except Exception:
                            current_app.logger.exception(
                                "bimonthly_title_fight_check: close_bidding(%s) failed", fight.id)
                current_app.logger.info("bimonthly_title_fight_check: complete")
            except Exception:
                current_app.logger.exception("bimonthly_title_fight_check failed")

    scheduler.add_job(
        bimonthly_title_fight_check,
        CronTrigger(day='1,15', hour='1', minute='0'),
        id='battlebugs_bimonthly_title_fights',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    def execute_ready_title_fights():
        """Execute title fights whose scheduled_date has passed."""
        with app.app_context():
            try:
                from app.services.championship_service import execute_title_fight
                from app.models import TitleFight
                from datetime import datetime, timezone as _tz
                now = datetime.now(_tz.utc)
                due = TitleFight.query.filter(
                    TitleFight.status == 'locked',
                    TitleFight.scheduled_date <= now,
                ).all()
                for fight in due:
                    try:
                        execute_title_fight(fight.id)
                        current_app.logger.info("Executed title fight %s", fight.id)
                    except Exception:
                        current_app.logger.exception("execute_title_fight(%s) failed", fight.id)
            except Exception:
                current_app.logger.exception("execute_ready_title_fights failed")

    scheduler.add_job(
        execute_ready_title_fights,
        'interval',
        hours=6,
        id='battlebugs_execute_title_fights',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    scheduler.start()
    app._battlebugs_scheduler_started = True
    app._battlebugs_scheduler = scheduler


# ── Season lifecycle ──────────────────────────────────────────────────────────

def advance_season_phases() -> None:
    """Advance season phases based on current time."""
    from app.models import Season

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seasons = Season.query.filter(Season.phase.notin_(['completed'])).all()
    for season in seasons:
        if season.phase == 'registration' and now >= season.registration_closes:
            _start_regular_season(season)
        elif season.phase == 'regular_season' and now >= season.regular_season_end:
            _start_season_tournament(season)
        elif season.phase == 'tournament':
            t = season.playoff
            if t:
                if t.format == 'round_robin':
                    _finalize_round_robin_tournament(season, t)
                elif t.status == 'completed' and t.winner_id:
                    season.phase = 'completed'
                    _retire_season_participants(season)
                    db.session.commit()
                    current_app.logger.info("Season %s completed. Champion: bug#%s", season.season_key, t.winner_id)
    db.session.commit()


def _start_regular_season(season) -> None:
    """Generate the weekly match schedule and advance phase to regular_season."""
    from app.models import SeasonRegistration, SeasonMatch

    regs = season.registrations.all()
    if len(regs) < 2:
        current_app.logger.info("Season %s has <2 registrants, skipping.", season.season_key)
        return

    # Randomly distribute unassigned boost points that were never claimed
    _distribute_unassigned_boost_points(regs)

    # Round-robin pairing for 7 days (each bug plays once per day against a random opponent)
    start = max(season.regular_season_start, datetime.now(timezone.utc).replace(tzinfo=None, hour=12, minute=0, second=0))
    bug_ids = [r.bug_id for r in regs]
    for day in range(1, 8):
        scheduled_at = start + timedelta(days=day - 1)
        pairs = _pair_bugs_for_day(bug_ids)
        for b1_id, b2_id in pairs:
            match = SeasonMatch(
                season_id=season.id,
                bug1_id=b1_id,
                bug2_id=b2_id,
                scheduled_at=scheduled_at,
                day_number=day,
            )
            db.session.add(match)

    season.phase = 'regular_season'
    db.session.commit()
    current_app.logger.info("Season %s: regular season started, %d matches scheduled.", season.season_key, season.matches.count())


def _pair_bugs_for_day(bug_ids: list) -> list:
    """Create random non-repeating pairs. If odd count, one bug gets a bye."""
    ids = bug_ids[:]
    _random.shuffle(ids)
    pairs = []
    while len(ids) >= 2:
        pairs.append((ids.pop(), ids.pop()))
    return pairs


_MAX_TOURNAMENT_PARTICIPANTS = 8  # keeps round-robin in ~1 week at 3 matches/day


def _start_season_tournament(season) -> None:
    """Create a round-robin tournament for the season-ending week and schedule all matches."""
    import math
    from app.models import SeasonRegistration, Tournament, TournamentApplication, SeasonMatch

    regs = season.registrations.order_by(
        SeasonRegistration.season_wins.desc(),
        SeasonRegistration.season_losses.asc()
    ).all()

    # Award regular season champion accolade
    if regs:
        from app.services.achievements import award_achievement
        top_bug = db.session.get(Bug, regs[0].bug_id)
        if top_bug:
            award_achievement(
                top_bug, 'regular_season_champion', 'Regular Season Champion',
                '🥇', f'Finished atop the standings in {season.name}.', rarity='rare',
            )

    _distribute_unassigned_boost_points(regs)

    # Top N advance (or all if fewer)
    advancing = regs[:_MAX_TOURNAMENT_PARTICIPANTS]
    if len(advancing) < 2:
        season.phase = 'completed'
        _retire_season_participants(season)
        db.session.commit()
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    t_start = season.tournament_start or now
    t_end = season.tournament_end or (t_start + timedelta(days=7))

    t = Tournament(
        name=f'{season.name} — Round Robin',
        tier=season.tier,
        season_key=season.season_key,
        start_date=t_start,
        end_date=t_end,
        registration_deadline=now,
        status='active',
        max_participants=len(advancing),
        format='round_robin',
        submissions_per_user=1,
        created_by_id=None,
    )
    db.session.add(t)
    db.session.flush()

    for reg in advancing:
        app_entry = TournamentApplication(
            tournament_id=t.id,
            bug_id=reg.bug_id,
            user_id=reg.user_id,
            status='approved',
        )
        db.session.add(app_entry)

    # Schedule all round-robin matches as SeasonMatch records
    bug_ids = [r.bug_id for r in advancing]
    pairs = [(bug_ids[i], bug_ids[j])
             for i in range(len(bug_ids)) for j in range(i + 1, len(bug_ids))]
    _random.shuffle(pairs)

    days_available = max(7, (t_end - t_start).days)
    matches_per_day = max(1, min(3, math.ceil(len(pairs) / days_available)))

    for idx, (b1_id, b2_id) in enumerate(pairs):
        day_offset = idx // matches_per_day
        slot_in_day = idx % matches_per_day
        # Stagger within day: noon, 4 pm, 8 pm
        hour_offset = 12 + slot_in_day * 4
        scheduled_at = (t_start + timedelta(days=day_offset)).replace(
            hour=hour_offset % 24, minute=0, second=0, microsecond=0,
        )
        sm = SeasonMatch(
            season_id=season.id,
            bug1_id=b1_id,
            bug2_id=b2_id,
            scheduled_at=scheduled_at,
            day_number=day_offset + 1,
            match_type='tournament',
        )
        db.session.add(sm)

    season.tournament_id = t.id
    season.phase = 'tournament'
    db.session.commit()
    current_app.logger.info(
        "Season %s: round-robin tournament #%d created with %d bugs, %d matches.",
        season.season_key, t.id, len(advancing), len(pairs),
    )


def _finalize_round_robin_tournament(season, t) -> None:
    """Check if all tournament matches are done; crown champion if so."""
    from app.models import SeasonMatch, Battle

    tournament_matches = SeasonMatch.query.filter_by(
        season_id=season.id, match_type='tournament'
    ).all()

    if not tournament_matches:
        return
    if any(m.completed_at is None for m in tournament_matches):
        return  # still in progress

    # Count tournament wins per bug
    win_counts: dict[int, int] = {}
    for m in tournament_matches:
        if m.battle and m.battle.winner_id:
            bid = m.battle.winner_id
            win_counts[bid] = win_counts.get(bid, 0) + 1

    if not win_counts:
        return

    champion_id = max(win_counts, key=win_counts.get)

    # Award season champion accolade
    champ_bug = db.session.get(Bug, champion_id)
    if champ_bug:
        from app.services.achievements import award_achievement
        from app.services.economy import award_currency, ACHIEVEMENT_REWARDS
        award_achievement(
            champ_bug, 'season_champion', 'Season Champion',
            '🏆', f'Won the round-robin tournament in {season.name}.', rarity='legendary',
        )
        pts = ACHIEVEMENT_REWARDS.get('season_champion', 300)
        try:
            award_currency(champ_bug.owner, pts, f'Season champion: {season.name}')
        except Exception:
            pass

    t.winner_id = champion_id
    t.status = 'completed'
    season.phase = 'completed'
    _retire_season_participants(season)
    db.session.commit()
    current_app.logger.info(
        "Season %s round-robin finalized. Champion: bug#%s with %d wins.",
        season.season_key, champion_id, win_counts[champion_id],
    )


def _retire_season_participants(season) -> None:
    """Retire all bugs that competed in a season and award the season_veteran accolade."""
    from app.services.achievements import award_achievement
    from app.services.economy import award_currency, ACHIEVEMENT_REWARDS
    for reg in season.registrations.all():
        bug = db.session.get(Bug, reg.bug_id)
        if not bug or bug.is_retired:
            continue
        bug.is_retired = True
        bug.retired_at = datetime.now(timezone.utc)
        db.session.add(bug)
        award_achievement(
            bug,
            'season_veteran',
            'Season Veteran',
            '🎖️',
            f'Competed in {season.name} and earned their stripes.',
            rarity='uncommon',
        )


def _distribute_unassigned_boost_points(regs) -> None:
    """Randomly assign any pending boost points to a stat for each registration."""
    stats = ('attack', 'defense', 'speed', 'lethality', 'grip', 'cunning')
    for reg in regs:
        if reg.pending_boost_points > 0:
            stat = reg.boost_auto_stat or _random.choice(stats)
            reg.apply_pending_boost(stat)


def play_due_season_matches() -> None:
    """Auto-play any season matches whose scheduled_at has passed and aren't complete."""
    from app.models import SeasonMatch, SeasonRegistration
    from app.services.battle_engine import simulate_battle

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due = SeasonMatch.query.filter(
        SeasonMatch.completed_at.is_(None),
        SeasonMatch.scheduled_at <= now,
    ).all()

    for sm in due:
        try:
            bug1 = db.session.get(Bug, sm.bug1_id)
            bug2 = db.session.get(Bug, sm.bug2_id)
            if not bug1 or not bug2:
                continue

            # Randomly distribute any unassigned boost points before this match
            for bug_id in (sm.bug1_id, sm.bug2_id):
                reg = SeasonRegistration.query.filter_by(
                    season_id=sm.season_id, bug_id=bug_id).first()
                if reg and reg.pending_boost_points > 0:
                    _distribute_unassigned_boost_points([reg])

            battle = simulate_battle(bug1, bug2)
            sm.battle_id = battle.id
            sm.completed_at = datetime.now(timezone.utc)

            # Award boost points
            winner_id = battle.winner_id
            for bug_id in (sm.bug1_id, sm.bug2_id):
                reg = SeasonRegistration.query.filter_by(
                    season_id=sm.season_id, bug_id=bug_id).first()
                if not reg:
                    continue
                if bug_id == winner_id:
                    reg.season_wins = (reg.season_wins or 0) + 1
                    reg.pending_boost_points = (reg.pending_boost_points or 0) + 3
                    if reg.boost_auto_stat:
                        reg.apply_pending_boost(reg.boost_auto_stat)
                else:
                    reg.season_losses = (reg.season_losses or 0) + 1
                    reg.pending_boost_points = (reg.pending_boost_points or 0) + 1
                    if reg.boost_auto_stat:
                        reg.apply_pending_boost(reg.boost_auto_stat)

            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception("play_due_season_matches: failed for SeasonMatch #%d", sm.id)
