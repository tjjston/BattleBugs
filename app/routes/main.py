from flask import Blueprint, render_template, redirect, url_for
from flask import send_from_directory, current_app
from app import db
from app.models import Bug, Battle, Tournament, User, Notification, BugAchievement, Species
from sqlalchemy import desc, func
from app.services.permission_system import AdminUserManager
from app.services.news_service import get_current_season, get_recent_activity, get_cached_briefing
from app.services.seasonal_tournament import get_active_seasonal_tournament
from app.services.ecosystem_service import get_ecosystem_data
from flask_login import current_user, login_required
import json

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """Homepage — current season, active events, standings, and LLM news briefing."""
    season = get_current_season()

    # Active + upcoming events
    active_tournaments = Tournament.query.filter(
        Tournament.status.in_(['registration', 'active', 'in_progress'])
    ).order_by(Tournament.start_date).limit(3).all()

    upcoming_tournaments = Tournament.query.filter(
        Tournament.status.in_(['upcoming', 'registration'])
    ).order_by(Tournament.start_date).limit(5).all()

    # Season standings — active (non-retired) bugs ordered by wins
    top_bugs = Bug.query.filter_by(is_retired=False).order_by(
        desc(Bug.wins)
    ).limit(10).all()

    recent_battles = Battle.query.order_by(desc(Battle.battle_date)).limit(5).all()

    # LLM news briefing (cached 1 h)
    news_briefing = get_cached_briefing()

    # Seasonal flagship tournament
    seasonal_tournament = get_active_seasonal_tournament()

    # Quick arena stats
    total_bugs = Bug.query.count()
    total_battles = Battle.query.count()
    total_retired = Bug.query.filter_by(is_retired=True).count()

    # Championship Circuit — current belt holders for dashboard tiles
    circuit_champions = []
    try:
        from app.models import TierChampionship
        CIRCUIT_TIERS = ['uber', 'ou', 'uu', 'ru', 'nu', 'zu']
        CIRCUIT_LABELS = {'uber': 'Legendary', 'ou': 'Elite', 'uu': 'Strong',
                          'ru': 'Rising', 'nu': 'Newcomer', 'zu': 'Zero'}
        for t in CIRCUIT_TIERS:
            belt = TierChampionship.query.filter_by(tier=t).first()
            circuit_champions.append({
                'tier': t,
                'label': CIRCUIT_LABELS[t],
                'belt': belt,
            })
    except Exception:
        pass

    return render_template('index.html',
                           season=season,
                           active_tournaments=active_tournaments,
                           upcoming_tournaments=upcoming_tournaments,
                           tournaments=upcoming_tournaments,       # backwards compat
                           top_bugs=top_bugs,
                           bugs=top_bugs,                          # backwards compat
                           recent_battles=recent_battles,
                           battles=recent_battles,                 # backwards compat
                           news_briefing=news_briefing,
                           seasonal_tournament=seasonal_tournament,
                           total_bugs=total_bugs,
                           total_battles=total_battles,
                           total_retired=total_retired,
                           circuit_champions=circuit_champions)

@bp.route('/hall-of-fame')
def hall_of_fame():
    """Hall of Fame — retired champions and tournament winners."""
    retired = Bug.query.filter_by(is_retired=True)\
        .order_by(desc(Bug.wins)).all()
    top_active = Bug.query.filter_by(is_retired=False)\
        .filter((Bug.wins + Bug.losses) >= 5)\
        .order_by(desc(Bug.wins)).limit(20).all()
    tournaments = Tournament.query.filter_by(status='completed')\
        .order_by(desc(Tournament.end_date)).limit(10).all()
    return render_template('hall_of_fame.html',
                         retired=retired,
                         top_bugs=top_active,
                         tournaments=tournaments)


@bp.route('/leaderboards')
def leaderboards():
    """Multi-category leaderboard."""
    top_wins = Bug.query.filter(Bug.is_retired == False)\
        .order_by(desc(Bug.wins)).limit(20).all()
    top_win_rate = Bug.query.filter((Bug.wins + Bug.losses) >= 3)\
        .order_by(desc((Bug.wins * 100.0) / (Bug.wins + Bug.losses))).limit(20).all()
    top_collectors = User.query.order_by(desc(User.bugs_submitted)).limit(20).all()
    top_tournament = User.query.filter(User.tournaments_won > 0)\
        .order_by(desc(User.tournaments_won)).limit(20).all()
    top_elo = User.query.order_by(desc(User.elo)).limit(20).all()
    top_ap = User.query.filter(User.accolade_points > 0)\
        .order_by(desc(User.accolade_points)).limit(20).all()

    # Species pioneers
    pioneer_rows = db.session.query(
        User,
        func.count(BugAchievement.id).label('count')
    ).join(Bug, Bug.user_id == User.id)\
     .join(BugAchievement, (BugAchievement.bug_id == Bug.id) & (BugAchievement.achievement_type == 'species_pioneer'))\
     .group_by(User.id)\
     .order_by(desc('count')).limit(20).all()
    pioneer_users = [{'user': u, 'count': count} for u, count in pioneer_rows]

    # Season standings by tier — top bugs ranked by season wins in the most recent active season
    from app.models import Season, SeasonRegistration
    TIERS = ['uber', 'ou', 'uu', 'ru', 'nu', 'zu']
    TIER_LABELS = {'uber': 'Legendary', 'ou': 'Elite', 'uu': 'Strong',
                   'ru': 'Rising', 'nu': 'Newcomer', 'zu': 'Zero'}
    season_standings = {}
    for tier in TIERS:
        latest_season = Season.query.filter_by(tier=tier)\
            .order_by(Season.registration_opens.desc()).first()
        if not latest_season:
            continue
        rows = db.session.query(SeasonRegistration, Bug)\
            .join(Bug, SeasonRegistration.bug_id == Bug.id)\
            .filter(SeasonRegistration.season_id == latest_season.id)\
            .order_by(
                desc(SeasonRegistration.season_wins),
                SeasonRegistration.season_losses.asc(),
            ).limit(10).all()
        if rows:
            season_standings[tier] = {
                'season': latest_season,
                'label': TIER_LABELS.get(tier, tier.upper()),
                'rows': [{'reg': reg, 'bug': bug} for reg, bug in rows],
            }

    # P4P preview (top 5 for leaderboard tab)
    try:
        from app.services.championship_service import get_pfp_rankings
        pfp_preview = get_pfp_rankings(limit=10)
    except Exception:
        pfp_preview = []

    return render_template('leaderboards.html',
                           top_wins=top_wins, top_win_rate=top_win_rate,
                           top_collectors=top_collectors, top_tournament=top_tournament,
                           top_elo=top_elo, top_ap=top_ap, pioneer_users=pioneer_users,
                           season_standings=season_standings, tier_order=TIERS,
                           pfp_preview=pfp_preview)


@bp.route('/collection')
@login_required
def collection():
    """Current user's field journal and collection progress."""
    bugs = Bug.query.filter_by(user_id=current_user.id).order_by(Bug.submission_date.desc()).all()
    species_count = len({bug.species_id for bug in bugs if bug.species_id})
    sightings = [bug for bug in bugs if bug.location_found or bug.found_date or bug.latitude or bug.longitude]
    return render_template('collection.html', bugs=bugs, species_count=species_count, sightings=sightings)


@bp.route('/my-bugs')
@login_required
def my_bugs():
    """Bug manager — competition track enrollment and tier overview."""
    from app.models import Season, SeasonRegistration, TierRanking, TierChampionship

    all_bugs = Bug.query.filter_by(user_id=current_user.id)\
        .order_by(Bug.submission_date.desc()).all()

    TIERS = ['uber', 'ou', 'uu', 'ru', 'nu', 'zu']
    TIER_LABELS = {'uber': 'Legendary', 'ou': 'Elite', 'uu': 'Strong',
                   'ru': 'Rising', 'nu': 'Newcomer', 'zu': 'Zero'}

    # Build per-tier buckets — season and MMA separately
    season_by_tier = {t: [] for t in TIERS}
    mma_by_tier = {t: [] for t in TIERS}
    untracked = []

    for bug in all_bugs:
        if not bug.tier:
            continue
        if bug.bug_track == 'mma':
            mma_by_tier[bug.tier].append(bug)
        elif bug.bug_track == 'season':
            season_by_tier[bug.tier].append(bug)
        else:
            untracked.append(bug)

    # Active seasons open for registration per tier
    open_seasons = {}
    for t in TIERS:
        s = Season.query.filter_by(tier=t, phase='registration').first()
        if s:
            open_seasons[t] = s

    # MMA active-count per tier (for limit display)
    mma_active_count = {}
    for t in TIERS:
        mma_active_count[t] = Bug.query.filter(
            Bug.user_id == current_user.id,
            Bug.bug_track == 'mma',
            Bug.tier == t,
            Bug.is_retired == False,
        ).count()

    # Eligible open tournaments for the user's bugs
    from app.models import Tournament, TournamentApplication
    open_tournaments = Tournament.query.filter(
        Tournament.status.in_(['registration', 'upcoming'])
    ).order_by(Tournament.start_date).all()

    # Build set of (tournament_id, bug_id) already applied
    applied_pairs = set()
    if all_bugs:
        bug_ids = [b.id for b in all_bugs]
        apps = TournamentApplication.query.filter(
            TournamentApplication.bug_id.in_(bug_ids),
            TournamentApplication.status.in_(['pending', 'approved']),
        ).all()
        applied_pairs = {(a.tournament_id, a.bug_id) for a in apps}

    # Per tournament: which bugs are eligible
    tournament_eligibility = []
    for t in open_tournaments:
        eligible = []
        for bug in all_bugs:
            if bug.is_retired:
                continue
            if not bug.tier:
                continue
            if t.tier and t.tier != bug.tier:
                continue
            if (t.id, bug.id) not in applied_pairs:
                eligible.append(bug)
        already_in = [b for b in all_bugs if (t.id, b.id) in applied_pairs]
        tournament_eligibility.append({
            'tournament': t,
            'eligible': eligible,
            'already_in': already_in,
        })

    return render_template('my_bugs.html',
                           all_bugs=all_bugs,
                           season_by_tier=season_by_tier,
                           mma_by_tier=mma_by_tier,
                           untracked=untracked,
                           open_seasons=open_seasons,
                           mma_active_count=mma_active_count,
                           tier_labels=TIER_LABELS,
                           tiers=TIERS,
                           tournament_eligibility=tournament_eligibility)


@bp.route('/ecosystem')
def ecosystem():
    """Combat type matchup matrix and species relationship graph."""
    import json
    data = get_ecosystem_data()
    graph_json = json.dumps(data['species_graph'])
    return render_template('ecosystem.html', data=data, graph_json=graph_json)


@bp.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Serve user-uploaded files from the configured uploads folder."""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


@bp.route('/user/<int:user_id>')
def user_profile(user_id):
    """Public user profile with charts, badges and accolades."""
    user = db.get_or_404(User, user_id)
    stats = AdminUserManager.get_user_stats(user)
    recent_bugs = Bug.query.filter_by(user_id=user.id)\
        .order_by(Bug.submission_date.desc()).limit(10).all()
    all_bugs = Bug.query.filter_by(user_id=user.id).all()

    # Tier distribution
    tier_counts = {}
    for b in all_bugs:
        t = b.tier or 'unranked'
        tier_counts[t] = tier_counts.get(t, 0) + 1

    # Attack-type distribution
    type_counts = {}
    for b in all_bugs:
        t = b.attack_type or 'unknown'
        type_counts[t] = type_counts.get(t, 0) + 1

    # Avg stats
    if all_bugs:
        avg_stats = {
            'attack':   round(sum(b.attack or 0 for b in all_bugs) / len(all_bugs), 1),
            'defense':  round(sum(b.defense or 0 for b in all_bugs) / len(all_bugs), 1),
            'speed':    round(sum(b.speed or 0 for b in all_bugs) / len(all_bugs), 1),
            'lethality':round(sum(b.lethality or 50 for b in all_bugs) / len(all_bugs), 1),
            'grip':     round(sum(b.grip or 50 for b in all_bugs) / len(all_bugs), 1),
            'cunning':  round(sum(b.cunning or 50 for b in all_bugs) / len(all_bugs), 1),
        }
    else:
        avg_stats = {k: 0 for k in ('attack','defense','speed','lethality','grip','cunning')}

    # Species pioneer count (BugAchievement has no user_id; join through Bug)
    from app.models import Bug as _Bug
    pioneer_count = BugAchievement.query\
        .join(_Bug, BugAchievement.bug_id == _Bug.id)\
        .filter(_Bug.user_id == user.id, BugAchievement.achievement_type == 'species_pioneer').count()

    return render_template('user_profile.html', user=user, stats=stats,
                           recent_bugs=recent_bugs,
                           tier_counts=json.dumps(tier_counts),
                           type_counts=json.dumps(type_counts),
                           avg_stats=json.dumps(avg_stats),
                           pioneer_count=pioneer_count)


@bp.route('/me')
@login_required
def my_profile():
    """Redirect to the current user's public profile."""
    return redirect(url_for('main.user_profile', user_id=current_user.id))


@bp.route('/notifications')
@login_required
def notifications():
    """List all notifications for the current user and mark them read."""
    notifs = current_user.notifications\
        .order_by(Notification.created_at.desc()).all()
    unread_ids = [n.id for n in notifs if not n.is_read]
    if unread_ids:
        Notification.query.filter(Notification.id.in_(unread_ids))\
            .update({'is_read': True}, synchronize_session=False)
        db.session.commit()
    return render_template('notifications.html', notifications=notifs)


@bp.route('/notifications/<int:notif_id>/dismiss', methods=['POST'])
@login_required
def dismiss_notification(notif_id):
    """Mark a single notification as read (called from victory toast dismiss)."""
    from flask import jsonify
    notif = db.session.get(Notification, notif_id)
    if notif and notif.user_id == current_user.id:
        notif.is_read = True
        db.session.commit()
    return jsonify({'ok': True})


@bp.route('/tutorial')
def tutorial():
    return render_template('tutorial.html')


@bp.app_context_processor
def inject_unread_notifications():
    """Make unread notification count and unread victory banners available to all templates."""
    count = 0
    victory_banners = []
    if current_user.is_authenticated:
        count = current_user.notifications.filter_by(is_read=False).count()
        victory_banners = (
            current_user.notifications
            .filter_by(is_read=False, notification_type='tournament_victory')
            .order_by(Notification.created_at.desc())
            .limit(5)
            .all()
        )
    return {'unread_notification_count': count, 'victory_banners': victory_banners}
