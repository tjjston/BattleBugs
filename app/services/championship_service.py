"""
Championship Service — MMA-style per-tier belt system.

Tiers: uber | ou | uu | ru | nu | zu
- Each tier has a champion (belt holder) and up to 10 ranked contenders.
- Rankings recalculate weekly via background job.
- Top-3 contenders can bid AP for the bi-monthly title shot.
- Contenders can issue callouts to ranked rivals.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Optional

from flask import current_app

from app import db
from app.models import (
    Bug, Battle, User,
    TierChampionship, TierRanking, TitleFight, TitleBid, ContenderCallout,
    CHAMPIONSHIP_TIERS, CONTENDER_MIN_BIDS,
)

# Tier weights for P4P scoring (stronger tiers = more credit)
TIER_WEIGHTS = {'uber': 6.0, 'ou': 5.0, 'uu': 4.0, 'ru': 3.0, 'nu': 2.0, 'zu': 1.0}

# Bugs need this many total wins before they can enter rankings
MIN_WINS_FOR_RANKING = 5


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Ranking ───────────────────────────────────────────────────────────────────

def calculate_ranking_score(bug: Bug, tier: str) -> float:
    """
    Weighted win/loss score with recency decay and opponent-quality multiplier.
    Only battles from the last 180 days count. Inactivity decays score.
    """
    now = _now()
    cutoff = now - timedelta(days=180)

    battles = (
        Battle.query
        .filter(
            ((Battle.bug1_id == bug.id) | (Battle.bug2_id == bug.id)),
            Battle.battle_date >= cutoff,
        )
        .order_by(Battle.battle_date.desc())
        .all()
    )

    score = 0.0
    last_fight = None

    for b in battles:
        if last_fight is None:
            last_fight = b.battle_date
        if b.winner_id is None:
            continue  # draw

        won = b.winner_id == bug.id
        opp_id = b.bug2_id if b.bug1_id == bug.id else b.bug1_id

        # Recency weight
        days_ago = max(0, (now - b.battle_date).days)
        if days_ago <= 30:
            recency = 1.0
        elif days_ago <= 90:
            recency = 0.6
        else:
            recency = 0.3

        # Opponent quality: ranked opponents score more
        opp_ranking = TierRanking.query.filter_by(bug_id=opp_id, tier=tier).first()
        opp_rank = opp_ranking.rank if (opp_ranking and opp_ranking.rank) else 15
        if opp_rank <= 3:
            opp_quality = 3.0
        elif opp_rank <= 5:
            opp_quality = 2.0
        elif opp_rank <= 10:
            opp_quality = 1.5
        else:
            opp_quality = 1.0

        # Is opponent the champion?
        champ = TierChampionship.query.filter_by(tier=tier).first()
        if champ and champ.champion_bug_id == opp_id:
            opp_quality = max(opp_quality, 4.0)

        base = 10.0 if won else -3.0
        score += base * recency * opp_quality

    # Inactivity decay: -5 pts/week after 3 idle weeks
    if last_fight:
        weeks_idle = max(0, (now - last_fight).days / 7 - 3)
        score -= weeks_idle * 5

    return max(0.0, round(score, 2))


def recalculate_tier_rankings(tier: str) -> None:
    """Recompute ranking scores + assign ranks 1-10 for one tier."""
    eligible = (
        Bug.query
        .filter(
            Bug.bug_track == 'mma',
            Bug.tier == tier,
            Bug.wins >= MIN_WINS_FOR_RANKING,
            Bug.is_retired == False,
        )
        .all()
    )

    # Exclude the current champion from contender rankings
    champ = TierChampionship.query.filter_by(tier=tier).first()
    champ_id = champ.champion_bug_id if champ and champ.status == 'active' else None

    scored = []
    for bug in eligible:
        if bug.id == champ_id:
            continue
        score = calculate_ranking_score(bug, tier)
        scored.append((bug, score))

    scored.sort(key=lambda x: x[1], reverse=True)

    # Update or create TierRanking rows
    for position, (bug, score) in enumerate(scored, start=1):
        entry = TierRanking.query.filter_by(tier=tier, bug_id=bug.id).first()
        if entry is None:
            entry = TierRanking(tier=tier, bug_id=bug.id)
            db.session.add(entry)
        entry.ranking_score = score
        entry.rank = position if position <= 10 else None
        entry.last_updated = _now()

    # Remove rankings for bugs no longer eligible
    eligible_ids = {bug.id for bug, _ in scored}
    TierRanking.query.filter(
        TierRanking.tier == tier,
        ~TierRanking.bug_id.in_(eligible_ids),
    ).delete(synchronize_session=False)

    db.session.commit()


def recalculate_all_rankings() -> None:
    for tier in CHAMPIONSHIP_TIERS:
        try:
            recalculate_tier_rankings(tier)
        except Exception:
            current_app.logger.exception("Ranking recalc failed for tier %s", tier)


def get_contenders(tier: str, limit: int = 10) -> list[TierRanking]:
    return (
        TierRanking.query
        .filter_by(tier=tier)
        .filter(TierRanking.rank.isnot(None))
        .order_by(TierRanking.rank)
        .limit(limit)
        .all()
    )


# ── Championship / Title Fights ───────────────────────────────────────────────

def ensure_championships() -> None:
    """Create a vacant TierChampionship row for any tier that doesn't have one."""
    for tier in CHAMPIONSHIP_TIERS:
        if not TierChampionship.query.filter_by(tier=tier).first():
            db.session.add(TierChampionship(tier=tier, status='vacant'))
    db.session.commit()


def schedule_title_fights() -> None:
    """
    For each tier that has an active or vacant championship and no pending/bidding
    title fight, create one scheduled ~60 days out with a 7-day bidding window.
    """
    ensure_championships()
    now = _now()

    for champ in TierChampionship.query.all():
        # Skip if a fight is already pending
        pending = TitleFight.query.filter(
            TitleFight.tier == champ.tier,
            TitleFight.status.in_(['bidding', 'locked']),
        ).first()
        if pending:
            continue

        # Need at least a #1 contender to schedule
        top = TierRanking.query.filter_by(tier=champ.tier, rank=1).first()
        if not top:
            continue

        scheduled = now + timedelta(days=60)
        bid_closes = now + timedelta(days=7)

        fight = TitleFight(
            tier=champ.tier,
            championship_id=champ.id,
            scheduled_date=scheduled,
            bid_closes_at=bid_closes,
            status='bidding',
        )
        db.session.add(fight)

    db.session.commit()


def close_bidding(fight_id: int) -> Optional[TitleFight]:
    """
    Select the winning bidder (highest amount; rank breaks ties).
    Deduct AP from winner. Lock in the challenger.
    If no bids, #1 contender gets it free.
    """
    fight = db.session.get(TitleFight, fight_id)
    if not fight or fight.status != 'bidding':
        return None

    bids = (
        TitleBid.query
        .filter_by(fight_id=fight_id)
        .order_by(TitleBid.amount.desc(), TitleBid.contender_rank.asc())
        .all()
    )

    if bids:
        winner_bid = bids[0]
        winner_bid.won_bid = True
        fight.challenger_bug_id = winner_bid.bug_id
        # Deduct AP from the winning bidder
        if winner_bid.amount > 0:
            from app.services.economy import spend_currency
            try:
                spend_currency(
                    winner_bid.user,
                    winner_bid.amount,
                    f'title_bid_win:{fight_id}',
                    'title_fight',
                    fight_id,
                )
            except Exception:
                current_app.logger.warning("Could not deduct AP for title bid fight=%d", fight_id)
    else:
        # Default: #1 contender gets it for free
        top = TierRanking.query.filter_by(tier=fight.tier, rank=1).first()
        if top:
            fight.challenger_bug_id = top.bug_id

    fight.status = 'locked'
    db.session.commit()
    return fight


def execute_title_fight(fight_id: int) -> Optional[Battle]:
    """Run the title fight battle and update the championship."""
    fight = db.session.get(TitleFight, fight_id)
    if not fight or fight.status != 'locked' or not fight.challenger_bug_id:
        return None

    champ_record = fight.championship
    if not champ_record.champion_bug_id:
        # Vacant belt: challenger wins automatically
        _crown_champion(champ_record, db.session.get(Bug, fight.challenger_bug_id), fight)
        return None

    champion = db.session.get(Bug, champ_record.champion_bug_id)
    challenger = db.session.get(Bug, fight.challenger_bug_id)

    from app.services.battle_engine import simulate_battle
    battle = simulate_battle(champion, challenger)
    fight.battle_id = battle.id
    fight.status = 'completed'

    if battle.winner_id == challenger.id:
        _crown_champion(champ_record, challenger, fight)
        _award_badge(champion, 'mma_former_champion', 'Former Champion', '🥈',
                     'Held a tier championship belt', 'rare')
    else:
        # Successful defense
        champ_record.defense_count = (champ_record.defense_count or 0) + 1
        champ_record.next_defense_due = _now() + timedelta(days=60)
        _award_defense_badges(champion, champ_record.defense_count)

    db.session.commit()
    return battle


def _crown_champion(champ_record: TierChampionship, new_champ: Bug, fight: TitleFight) -> None:
    champ_record.champion_bug_id = new_champ.id
    champ_record.won_date = _now()
    champ_record.defense_count = 0
    champ_record.next_defense_due = _now() + timedelta(days=60)
    champ_record.status = 'active'

    _award_badge(new_champ, 'mma_champion',
                 f'{champ_record.tier.upper()} Champion', '🏆',
                 f'Won the {champ_record.tier.upper()} tier championship belt', 'legendary')

    # Remove new champ from contender rankings
    TierRanking.query.filter_by(tier=champ_record.tier, bug_id=new_champ.id).delete()

    # Former champ re-enters rankings at rank 2 (they just lost to #1)
    old_id = fight.championship.champion_bug_id
    if old_id and old_id != new_champ.id:
        old_entry = TierRanking.query.filter_by(tier=champ_record.tier, bug_id=old_id).first()
        if not old_entry:
            old_entry = TierRanking(tier=champ_record.tier, bug_id=old_id)
            db.session.add(old_entry)
        old_entry.rank = 2
        old_entry.ranking_score = calculate_ranking_score(
            db.session.get(Bug, old_id), champ_record.tier
        )
        old_entry.last_updated = _now()


def _award_defense_badges(champ: Bug, defense_count: int) -> None:
    milestones = {
        1: ('mma_first_defense', 'First Defense', '🛡️', 'Defended the championship belt once', 'uncommon'),
        3: ('mma_iron_reign', 'Iron Reign', '⚔️', 'Defended the championship belt 3 times', 'rare'),
        5: ('mma_dynasty', 'Dynasty', '👑', 'Defended the championship belt 5 times', 'legendary'),
    }
    if defense_count in milestones:
        _award_badge(champ, *milestones[defense_count])


def _award_badge(bug: Bug, achievement_type: str, name: str, icon: str,
                 description: str, rarity: str = 'common') -> None:
    from app.services.achievements import award_achievement
    try:
        award_achievement(bug, achievement_type, name, icon, description, rarity)
    except Exception:
        pass


# ── Bidding ───────────────────────────────────────────────────────────────────

def place_bid(fight_id: int, bug: Bug, user: User, amount: int) -> tuple[bool, str]:
    """
    Validate and record a title bid.
    Returns (success, message).
    """
    fight = db.session.get(TitleFight, fight_id)
    if not fight:
        return False, 'Title fight not found.'
    if fight.status != 'bidding':
        return False, 'Bidding window is closed.'
    if _now() > fight.bid_closes_at:
        return False, 'Bidding deadline has passed.'

    # Check bug is in top-3 contenders for this tier
    ranking = TierRanking.query.filter_by(tier=fight.tier, bug_id=bug.id).first()
    if not ranking or not ranking.rank or ranking.rank > 3:
        return False, 'Only the top-3 contenders may bid for the title shot.'

    min_bid = CONTENDER_MIN_BIDS.get(ranking.rank, 999)
    if amount < min_bid:
        return False, f'Rank #{ranking.rank} contenders must bid at least {min_bid} AP.'

    if (user.accolade_points or 0) < amount:
        return False, f'Insufficient AP. You have {user.accolade_points or 0}, bid requires {amount}.'

    # One bid per bug per fight
    existing = TitleBid.query.filter_by(fight_id=fight_id, bug_id=bug.id).first()
    if existing:
        existing.amount = amount  # allow updating your bid
        existing.placed_at = _now()
    else:
        db.session.add(TitleBid(
            fight_id=fight_id,
            bug_id=bug.id,
            user_id=user.id,
            amount=amount,
            contender_rank=ranking.rank,
            min_required=min_bid,
        ))
    db.session.commit()
    return True, f'Bid of {amount} AP placed successfully!'


# ── Callouts ──────────────────────────────────────────────────────────────────

def issue_callout(challenger: Bug, target: Bug) -> tuple[bool, str]:
    """Challenger (ranked) calls out target (ranked). Must be within 3 ranks."""
    if challenger.tier != target.tier:
        return False, 'Bugs must be in the same tier.'

    tier = challenger.tier
    cr = TierRanking.query.filter_by(tier=tier, bug_id=challenger.id).first()
    tr = TierRanking.query.filter_by(tier=tier, bug_id=target.id).first()

    if not cr or not cr.rank:
        return False, f'{challenger.nickname} is not in the top-10 contenders.'
    if not tr or not tr.rank:
        return False, f'{target.nickname} is not in the top-10 contenders.'
    if abs(cr.rank - tr.rank) > 3:
        return False, 'You can only call out bugs within 3 ranks of your position.'

    # One pending callout at a time per challenger
    active = ContenderCallout.query.filter_by(
        challenger_bug_id=challenger.id, status='pending'
    ).first()
    if active:
        return False, f'{challenger.nickname} already has a pending callout.'

    callout = ContenderCallout(
        tier=tier,
        challenger_bug_id=challenger.id,
        target_bug_id=target.id,
        expires_at=_now() + timedelta(days=7),
    )
    db.session.add(callout)
    db.session.commit()
    return True, f'{challenger.nickname} has called out {target.nickname}! They have 7 days to respond.'


def respond_callout(callout_id: int, accept: bool) -> tuple[bool, str]:
    """Target accepts or declines a callout."""
    callout = db.session.get(ContenderCallout, callout_id)
    if not callout or callout.status != 'pending':
        return False, 'Callout not found or already resolved.'

    if not accept:
        callout.status = 'declined'
        db.session.commit()
        return True, 'Callout declined.'

    # Fight!
    challenger = callout.challenger
    target = callout.target
    from app.services.battle_engine import simulate_battle
    battle = simulate_battle(challenger, target)

    callout.battle_id = battle.id
    callout.status = 'completed'

    # Adjust rankings based on result
    _update_rankings_after_callout(callout, battle)

    db.session.commit()
    return True, f'The bout is set! {challenger.nickname} vs {target.nickname}.'


def _update_rankings_after_callout(callout: ContenderCallout, battle: Battle) -> None:
    tier = callout.tier
    cr = TierRanking.query.filter_by(tier=tier, bug_id=callout.challenger_bug_id).first()
    tr = TierRanking.query.filter_by(tier=tier, bug_id=callout.target_bug_id).first()

    if not cr or not tr:
        return

    winner_id = battle.winner_id
    if winner_id == callout.challenger_bug_id and cr.rank > tr.rank:
        # Upset: challenger was lower-ranked and won — swap positions
        cr.rank, tr.rank = tr.rank, cr.rank
    elif winner_id == callout.target_bug_id and tr.rank > cr.rank:
        # Target was lower-ranked and won — swap
        cr.rank, tr.rank = tr.rank, cr.rank

    cr.last_fight_date = _now()
    tr.last_fight_date = _now()

    # Award contender badges
    for entry in (cr, tr):
        bug = db.session.get(Bug, entry.bug_id)
        if entry.rank == 1:
            _award_badge(bug, 'mma_contender_1', '#1 Contender', '🥊',
                         'Reached #1 contender status', 'rare')
        elif entry.rank <= 3:
            _award_badge(bug, 'mma_contender_top3', 'Top 3 Contender', '🎯',
                         'Reached top-3 contender status', 'uncommon')
        elif entry.rank <= 10:
            _award_badge(bug, 'mma_contender_top10', 'Top 10 Contender', '📋',
                         'Reached top-10 contender status', 'common')


# ── P4P ──────────────────────────────────────────────────────────────────────

def calculate_pfp_score(bug: Bug) -> float:
    """
    Cross-tier pound-for-pound score — tiers treated equally.
    A perfect ZU champion outranks an average Uber champion.
    Formula: championship_status_bonus + win_rate_bonus + defense_bonus
    """
    wins = bug.wins or 0
    losses = bug.losses or 0
    total = wins + losses
    win_rate = wins / total if total > 0 else 0.0

    champ = TierChampionship.query.filter_by(
        tier=bug.tier, champion_bug_id=bug.id, status='active'
    ).first()
    ranking = TierRanking.query.filter_by(bug_id=bug.id).first()

    if champ:
        # Champions: 300 base + win rate (up to 100) + 25 per title defense
        pos_score = 300.0 + win_rate * 100.0 + (champ.defense_count or 0) * 25.0
    elif ranking and ranking.rank:
        # Contenders: 150/120/90... scaled by rank + win rate bonus
        rank_base = max(0.0, 160.0 - ranking.rank * 15.0)
        pos_score = rank_base + win_rate * 60.0
    else:
        pos_score = win_rate * 20.0

    return round(pos_score, 2)


def get_pfp_rankings(limit: int = 20) -> list[dict]:
    """Return top bugs cross-tier sorted by P4P score."""
    candidates = Bug.query.filter(
        Bug.bug_track == 'mma',
        Bug.wins >= MIN_WINS_FOR_RANKING,
        Bug.is_retired == False,
    ).all()

    scored = [(bug, calculate_pfp_score(bug)) for bug in candidates]
    scored.sort(key=lambda x: x[1], reverse=True)

    return [
        {'rank': i + 1, 'bug': bug, 'score': score}
        for i, (bug, score) in enumerate(scored[:limit])
    ]


def expire_stale_callouts() -> None:
    """Mark pending callouts older than their expiry as expired."""
    stale = ContenderCallout.query.filter(
        ContenderCallout.status == 'pending',
        ContenderCallout.expires_at < _now(),
    ).all()
    for c in stale:
        c.status = 'expired'
    if stale:
        db.session.commit()
