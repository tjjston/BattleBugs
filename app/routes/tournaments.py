from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import Tournament, Bug, Battle
from datetime import datetime

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
    battles = Battle.query.filter_by(tournament_id=tournament_id)\
        .order_by(Battle.round_number, Battle.battle_date).all()
    
    return render_template('tournament_view.html', 
                         tournament=tournament,
                         battles=battles)

@bp.route('/tournament/create', methods=['GET', 'POST'])
@login_required
def create_tournament():
    if request.method == 'POST':
        name = request.form.get('name')
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d')
        
        tournament = Tournament(
            name=name,
            start_date=start_date,
            status='upcoming',
            created_by=current_user.id,
            entries = len(bug.ids for bug in Bug.query.all())
        )
        
        db.session.add(tournament)
        db.session.commit()
        
        flash(f'Tournament "{name}" created!', 'success')
        return redirect(url_for('tournaments.view_tournament', tournament_id=tournament.id))
    
    return render_template('tournament_create.html')

@bp.route('/tournament/<int:tournament_id>/start', methods=['POST'])
@login_required
def start_tournament(tournament_id):
    tournament = Tournament.query.get_or_404(tournament_id)
    
    if tournament.status != 'upcoming':
        flash('Tournament already started or completed', 'warning')
        return redirect(url_for('tournaments.view_tournament', tournament_id=tournament_id))
    
    tournament.status = 'active'
    db.session.commit()
    
    flash(f'Tournament "{tournament.name}" has begun!', 'success')
    return redirect(url_for('tournaments.view_tournament', tournament_id=tournament_id))