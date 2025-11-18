from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import Tournament, Bug, Battle, TournamentApplication, TournamentMatch
from app.services.permission_system import require_role, UserRole
from datetime import datetime
from app.services.tournament_system import TournamentManager, TournamentEligibilityChecker
import random

bp = Blueprint('tournaments', __name__)

@bp.route('/tournaments')
def list_tournaments():

    upcoming = Tournament.query.filter_by(status='upcoming').all()
    active = Tournament.query.filter_by(status='active').all()
    completed = Tournament.query.filter_by(status='completed')\
        .order_by(Tournament.end_date.desc()).all()
    
    return render_template('tournament_list.html',
                         upcoming=upcoming,
                         active=active,
                         completed=completed)

@bp.route('/tournament/<int:tournament_id>')
def view_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    battles = Battle.query.filter_by(tournament_id=tournament_id).order_by(Battle.round_number, Battle.battle_date).all()

    # If no Battle records exist yet, fall back to TournamentMatch bracket structure
    if not battles:
        from types import SimpleNamespace
        matches = TournamentMatch.query.filter_by(tournament_id=tournament_id).order_by(TournamentMatch.round_number, TournamentMatch.match_number).all()
        # Map matches to lightweight objects that the template expects (id, round_number, bug1, bug2, battle_date, winner)
        battles = []
        for m in matches:
            obj = SimpleNamespace()
            obj.id = m.id
            obj.round_number = getattr(m, 'round_number', None)
            obj.bug1 = m.bug1
            obj.bug2 = m.bug2
            obj.battle_date = None
            obj.winner = getattr(m, 'winner', None)
            battles.append(obj)

    return render_template('tournament_view.html', tournament=tournament, battles=battles)


@bp.route('/tournament/<int:tournament_id>/apply', methods=['GET', 'POST'])
@login_required
def apply_tournament(tournament_id):
    """Allow a logged-in user to apply one of their eligible bugs to a tournament."""
    tournament = Tournament.query.get_or_404(tournament_id)

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
    tournament = Tournament.query.get_or_404(tournament_id)

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

        db.session.commit()
        flash('Tournament updated', 'success')
        return redirect(url_for('tournaments.view_tournament', tournament_id=tournament.id))

    return render_template('tournament_edit.html', tournament=tournament)


@bp.route('/tournament/<int:tournament_id>/delete', methods=['POST'])
@require_role(UserRole.MODERATOR)
def delete_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)

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

        # Create tournament using only supported model fields
        tournament = Tournament(
            name=name,
            start_date=start_date,
            status='upcoming'
        )

        # Registration deadline: optional. Support an explicit "no deadline" checkbox.
        no_deadline = request.form.get('no_deadline') == '1'
        reg_deadline_raw = request.form.get('registration_deadline')
        if no_deadline:
            tournament.registration_deadline = None
        elif reg_deadline_raw:
            try:
                tournament.registration_deadline = datetime.strptime(reg_deadline_raw, '%Y-%m-%d')
            except ValueError:
                flash('Invalid registration deadline; ignoring.', 'warning')

        # Optional max participants
        max_participants = request.form.get('max_participants')
        if max_participants:
            try:
                tournament.max_participants = int(max_participants)
            except ValueError:
                flash('Invalid participants number; ignoring.', 'warning')
        # Tier restriction and allow above
        tier = request.form.get('tier')
        if tier:
            tournament.tier = tier
            allow_above = request.form.get('allow_tier_above')
            tournament.allow_tier_above = True if allow_above == '1' else False
        
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
    tournament = Tournament.query.get_or_404(tournament_id)
    
    if tournament.status != 'upcoming':
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