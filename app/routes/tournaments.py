from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Tournament, Bug, Battle, TournamentApplication, TournamentMatch, Season, SeasonRegistration, SeasonMatch
from app.services.permission_system import require_role, UserRole
from datetime import datetime, timezone, timedelta
from app.services.tournament_system import TournamentManager, TournamentEligibilityChecker
from app.services.seasonal_tournament import ensure_seasonal_tournament
import random

bp = Blueprint('tournaments', __name__)

@bp.route('/tournaments')
def list_tournaments():
    # Create this season's championship if it doesn't exist yet
    try:
        ensure_seasonal_tournament()
    except Exception:
        pass

    upcoming = Tournament.query.filter(
        Tournament.status.in_(['upcoming', 'registration'])
    ).all()
    active = Tournament.query.filter_by(status='active').all()
    completed = Tournament.query.filter_by(status='completed')\
        .order_by(Tournament.end_date.desc()).all()

    return render_template('tournament_list.html',
                           upcoming=upcoming,
                           active=active,
                           completed=completed)

@bp.route('/tournament/<int:tournament_id>')
def view_tournament(tournament_id):
    tournament = db.get_or_404(Tournament, tournament_id)
    # Prefer TournamentMatch bracket structure and build columns server-side
    matches = TournamentMatch.query.filter_by(tournament_id=tournament_id).order_by(TournamentMatch.round_number, TournamentMatch.match_number).all()
    if matches:
        matches_by_round = {}
        for m in matches:
            rn = m.round_number or 1
            matches_by_round.setdefault(rn, []).append(m)
        # sort rounds
        rounds_sorted = sorted(matches_by_round.keys())
        return render_template('tournament_view.html', tournament=tournament, matches_by_round=matches_by_round, rounds_sorted=rounds_sorted)

    # Fallback: if no TournamentMatch entries, show Battle rows (older flow)
    battles = Battle.query.filter_by(tournament_id=tournament_id).order_by(Battle.round_number, Battle.battle_date).all()
    return render_template('tournament_view.html', tournament=tournament, battles=battles)


@bp.route('/tournament/<int:tournament_id>/bracket_data')
def tournament_bracket_data(tournament_id):
    """Return structured bracket data (JSON) for live-updating front-end."""
    tournament = db.get_or_404(Tournament, tournament_id)

    # Prefer TournamentMatch records if present, otherwise use Battle entries
    matches = TournamentMatch.query.filter_by(tournament_id=tournament_id).order_by(TournamentMatch.round_number, TournamentMatch.match_number).all()
    nodes = []
    if matches:
        for m in matches:
            def serial_bug(bug):
                if not bug:
                    return None
                # Try to find a seed from TournamentApplication if present
                seed = None
                try:
                    app_row = TournamentApplication.query.filter_by(tournament_id=tournament_id, bug_id=bug.id).first()
                    if app_row and getattr(app_row, 'seed_number', None):
                        seed = app_row.seed_number
                except Exception:
                    seed = None

                return {
                    'id': bug.id,
                    'nickname': bug.nickname,
                    'seed': seed,
                    'attack': bug.attack,
                    'defense': bug.defense,
                    'speed': bug.speed,
                    'wins': bug.wins,
                    'losses': bug.losses,
                    'flair': bug.flair,
                }

            nodes.append({
                'id': m.id,
                'round': m.round_number,
                'match': m.match_number,
                'bug1': serial_bug(m.bug1),
                'bug2': serial_bug(m.bug2),
                'winner_id': m.winner_id,
                'battle_id': m.battle_id,
                'scheduled_for': m.scheduled_for.isoformat() if m.scheduled_for else None,
                'completed_at': m.completed_at.isoformat() if m.completed_at else None,
                'next_match_id': m.next_match_id,
            })
    else:
        battles = Battle.query.filter_by(tournament_id=tournament_id).order_by(Battle.round_number, Battle.battle_date).all()
        for b in battles:
            nodes.append({
                'id': b.id,
                'round': b.round_number,
                'match': None,
                'bug1': {'id': b.bug1.id, 'nickname': b.bug1.nickname, 'attack': b.bug1.attack, 'defense': b.bug1.defense, 'speed': b.bug1.speed, 'flair': b.bug1.flair},
                'bug2': {'id': b.bug2.id, 'nickname': b.bug2.nickname, 'attack': b.bug2.attack, 'defense': b.bug2.defense, 'speed': b.bug2.speed, 'flair': b.bug2.flair},
                'winner_id': b.winner_id,
                'battle_id': b.id,
                'scheduled_for': b.battle_date.isoformat() if b.battle_date else None,
                'completed_at': b.battle_date.isoformat() if b.battle_date else None,
                'next_match_id': None,
            })

    return jsonify({
        'tournament_id': tournament.id,
        'tournament_name': tournament.name,
        'status': tournament.status,
        'nodes': nodes
    })


@bp.route('/tournament/<int:tournament_id>/apply', methods=['GET', 'POST'])
@login_required
def apply_tournament(tournament_id):
    """Allow a logged-in user to apply one of their eligible bugs to a tournament."""
    tournament = db.get_or_404(Tournament, tournament_id)

    # GET: show eligible bugs owned by user
    if request.method == 'GET':
        eligible = TournamentEligibilityChecker.get_eligible_bugs_for_user(current_user.id, tournament)
        return render_template('tournament_apply.html', tournament=tournament, eligible_bugs=eligible)

    # POST: submit application for selected bug
    bug_id = request.form.get('bug_id', type=int)
    if not bug_id:
        flash('Please select a bug to apply with.', 'warning')
        return redirect(url_for('tournaments.apply_tournament', tournament_id=tournament_id))

    try:
        application = TournamentManager.apply_to_tournament(bug_id=bug_id, tournament_id=tournament_id, user_id=current_user.id)
        flash('Application submitted! Waiting for approval.', 'success')
        return redirect(url_for('tournaments.view_tournament', tournament_id=tournament_id))
    except Exception as e:
        flash(f'Could not apply: {e}', 'danger')
        return redirect(url_for('tournaments.apply_tournament', tournament_id=tournament_id))


@bp.route('/tournament/<int:tournament_id>/edit', methods=['GET', 'POST'])
@require_role(UserRole.MODERATOR)
def edit_tournament(tournament_id):
    tournament = db.get_or_404(Tournament, tournament_id)

    if request.method == 'POST':
        tournament.name = request.form.get('name') or tournament.name
        sd = request.form.get('start_date')
        if sd:
            tournament.start_date = datetime.strptime(sd, '%Y-%m-%d')

        max_participants = request.form.get('max_participants')
        if max_participants:
            try:
                tournament.max_participants = int(max_participants)
            except ValueError:
                flash('Invalid participants number; ignored.', 'warning')

        tier = request.form.get('tier')
        tournament.tier = tier if tier else None
        tournament.allow_tier_above = True if request.form.get('allow_tier_above') == '1' else False
        tournament.retirement_event = request.form.get('retirement_event') == '1'

        db.session.commit()
        flash('Tournament updated', 'success')
        return redirect(url_for('tournaments.view_tournament', tournament_id=tournament.id))

    return render_template('tournament_edit.html', tournament=tournament)


@bp.route('/tournament/<int:tournament_id>/delete', methods=['POST'])
@require_role(UserRole.MODERATOR)
def delete_tournament(tournament_id):
    tournament = db.get_or_404(Tournament, tournament_id)

    # Remove related matches, applications, and battles safely
    TournamentMatch.query.filter_by(tournament_id=tournament.id).delete()
    TournamentApplication.query.filter_by(tournament_id=tournament.id).delete()
    Battle.query.filter_by(tournament_id=tournament.id).delete()
    db.session.delete(tournament)
    db.session.commit()

    flash('Tournament deleted', 'info')
    return redirect(url_for('tournaments.list_tournaments'))

@bp.route('/tournament/create', methods=['GET', 'POST'])
@login_required
def create_tournament():
    if request.method == 'POST':
        name = request.form.get('name')
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d')

        # Validate max participants
        max_participants = None
        max_participants_raw = request.form.get('max_participants')
        if max_participants_raw:
            try:
                max_participants = int(max_participants_raw)
                if max_participants < 2:
                    flash('Tournament must allow at least 2 participants.', 'danger')
                    return redirect(url_for('tournaments.create_tournament'))
            except ValueError:
                flash('Invalid participants number; ignoring.', 'warning')

        # Validate registration deadline
        registration_deadline = None
        no_deadline = request.form.get('no_deadline') == '1'
        reg_deadline_raw = request.form.get('registration_deadline')
        if not no_deadline and reg_deadline_raw:
            try:
                registration_deadline = datetime.strptime(reg_deadline_raw, '%Y-%m-%d')
                if registration_deadline >= start_date:
                    flash('Registration deadline must be before the tournament start date.', 'danger')
                    return redirect(url_for('tournaments.create_tournament'))
            except ValueError:
                flash('Invalid registration deadline; ignoring.', 'warning')

        tournament = Tournament(
            name=name,
            start_date=start_date,
            status='registration',
            max_participants=max_participants,
            registration_deadline=registration_deadline,
        )

        # Tier restriction and allow above
        tier = request.form.get('tier')
        if tier:
            tournament.tier = tier
            allow_above = request.form.get('allow_tier_above')
            tournament.allow_tier_above = True if allow_above == '1' else False

        tournament.retirement_event = request.form.get('retirement_event') == '1'

        db.session.add(tournament)
        db.session.commit()

        flash(f'Tournament "{name}" created!', 'success')
        return redirect(url_for('tournaments.view_tournament', tournament_id=tournament.id))
    
    return render_template('tournament_create.html')

def generate_tournament_bracket(tournament: Tournament):
    """Generate initial bracket for the tournament."""
    bugs = Bug.query.all()

    # If tournament limits participants, take the first N after shuffling
    random.shuffle(bugs)
    if getattr(tournament, 'max_participants', None):
        limit = int(tournament.max_participants)
        bugs = bugs[:limit]
    
    # Pair bugs for first round battles
    battles = []
    round_number = 1
    for i in range(0, len(bugs), 2):
        if i + 1 < len(bugs):
            battle = Battle(
                bug1_id=bugs[i].id,
                bug2_id=bugs[i+1].id,
                tournament_id=tournament.id,
                round_number=round_number,
                battle_date=None 
            )
            battles.append(battle)
            db.session.add(battle)
    
    db.session.commit()
    return battles



@bp.route('/tournament/<int:tournament_id>/start', methods=['POST'])
@login_required
def start_tournament(tournament_id):
    tournament = db.get_or_404(Tournament, tournament_id)
    
    if tournament.status not in ('upcoming', 'registration'):
        flash('Tournament already started or completed', 'warning')
        return redirect(url_for('tournaments.view_tournament', tournament_id=tournament_id))
    # Generate bracket using TournamentManager which uses approved applications
    try:
        matches = TournamentManager.generate_bracket(tournament.id)
    except Exception as e:
        flash(f'Failed to generate bracket: {e}', 'danger')
        return redirect(url_for('tournaments.view_tournament', tournament_id=tournament_id))

    tournament.status = 'active'
    db.session.commit()

    flash(f'Tournament "{tournament.name}" has begun! Generated {len(matches)} matches.', 'success')
    return redirect(url_for('tournaments.view_tournament', tournament_id=tournament_id))


# ── Season routes ─────────────────────────────────────────────────────────────

@bp.route('/seasons')
def list_seasons():
    active_seasons = (
        Season.query
        .filter(Season.phase.notin_(['completed']))
        .order_by(Season.registration_opens.desc())
        .all()
    )
    archived_seasons = (
        Season.query
        .filter_by(phase='completed')
        .order_by(Season.regular_season_end.desc())
        .all()
    )
    return render_template('season_list.html',
                           active_seasons=active_seasons,
                           archived_seasons=archived_seasons)


@bp.route('/season/<int:season_id>')
def view_season(season_id):
    season = db.get_or_404(Season, season_id)
    registrations = season.registrations.order_by(
        SeasonRegistration.season_wins.desc(),
        SeasonRegistration.season_losses.asc()
    ).all()
    today_matches = season.matches.filter(
        SeasonMatch.scheduled_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0),
        SeasonMatch.scheduled_at < datetime.now(timezone.utc).replace(hour=23, minute=59, second=59),
    ).all()
    my_reg = None
    if current_user.is_authenticated:
        my_reg = season.registrations.filter_by(user_id=current_user.id).first()

    # Schedule: group all matches by day_number for the schedule tab
    all_matches = season.matches.order_by(SeasonMatch.day_number, SeasonMatch.scheduled_at).all()
    schedule_by_day = {}
    for m in all_matches:
        schedule_by_day.setdefault(m.day_number, []).append(m)

    return render_template('season_detail.html', season=season, registrations=registrations,
                           today_matches=today_matches, my_reg=my_reg,
                           schedule_by_day=schedule_by_day)


@bp.route('/season/<int:season_id>/register', methods=['POST'])
@login_required
def register_for_season(season_id):
    season = db.get_or_404(Season, season_id)
    if season.phase != 'registration':
        flash('Registration is closed for this season.', 'danger')
        return redirect(url_for('tournaments.view_season', season_id=season_id))
    bug_id = request.form.get('bug_id', type=int)
    if not bug_id:
        flash('Select a bug to register.', 'danger')
        return redirect(url_for('tournaments.view_season', season_id=season_id))
    bug = db.session.get(Bug, bug_id)
    if not bug or bug.user_id != current_user.id:
        flash('Invalid bug selection.', 'danger')
        return redirect(url_for('tournaments.view_season', season_id=season_id))
    if season.tier and bug.tier != season.tier:
        flash(f'This season is restricted to {season.tier.upper()} tier bugs.', 'danger')
        return redirect(url_for('tournaments.view_season', season_id=season_id))
    existing = season.registrations.filter_by(bug_id=bug_id).first()
    if existing:
        flash(f'{bug.nickname} is already registered.', 'warning')
        return redirect(url_for('tournaments.view_season', season_id=season_id))
    count = season.registrations.count()
    if season.max_registrations and count >= season.max_registrations:
        flash('Season is full.', 'danger')
        return redirect(url_for('tournaments.view_season', season_id=season_id))
    reg = SeasonRegistration(season_id=season.id, bug_id=bug_id, user_id=current_user.id)
    db.session.add(reg)
    db.session.commit()
    flash(f'{bug.nickname} registered for {season.name}!', 'success')
    return redirect(url_for('tournaments.view_season', season_id=season_id))


@bp.route('/season/boost/<int:reg_id>/assign', methods=['POST'])
@login_required
def assign_boost_points(reg_id):
    """Manually assign pending boost points to a chosen stat."""
    reg = db.get_or_404(SeasonRegistration, reg_id)
    if reg.user_id != current_user.id:
        flash('Not your registration.', 'danger')
        return redirect(url_for('tournaments.list_seasons'))
    stat = request.form.get('stat', '').strip()
    pts = reg.apply_pending_boost(stat)
    if pts:
        db.session.commit()
        flash(f'+{pts} boost points applied to {stat} for {reg.bug.nickname}!', 'success')
    else:
        flash('No pending points or invalid stat.', 'warning')
    return redirect(url_for('tournaments.view_season', season_id=reg.season_id))


@bp.route('/season/boost/<int:reg_id>/auto', methods=['POST'])
@login_required
def set_boost_auto(reg_id):
    """Set or clear the auto-assign stat for a registration."""
    reg = db.get_or_404(SeasonRegistration, reg_id)
    if reg.user_id != current_user.id:
        flash('Not your registration.', 'danger')
        return redirect(url_for('tournaments.list_seasons'))
    stat = request.form.get('stat', '').strip() or None
    valid = ('attack', 'defense', 'speed', 'lethality', 'grip', 'cunning')
    if stat and stat not in valid:
        flash('Invalid stat.', 'danger')
        return redirect(url_for('tournaments.view_season', season_id=reg.season_id))
    reg.boost_auto_stat = stat
    db.session.commit()
    msg = f'Auto-boost set to {stat}.' if stat else 'Auto-boost cleared — you\'ll assign manually.'
    flash(msg, 'success')
    return redirect(url_for('tournaments.view_season', season_id=reg.season_id))