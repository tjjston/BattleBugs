from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app import db
from app.models import Bug, Battle, TournamentMatch
from app.services.battle_engine import simulate_battle

bp = Blueprint('battles', __name__)

@bp.route('/battles')
def list_battles():
    page = request.args.get('page', 1, type=int)
    battles = Battle.query.order_by(Battle.battle_date.desc())\
        .paginate(page=page, per_page=10, error_out=False)
    
    return render_template('battle_list.html', battles=battles)

@bp.route('/battle/<int:battle_id>')
def view_battle(battle_id):
    battle = Battle.query.get_or_404(battle_id)
    return render_template('battle_view.html', battle=battle)

@bp.route('/battle/new', methods=['GET', 'POST'])
@login_required
def new_battle():
    if request.method == 'POST':
        bug1_id = request.form.get('bug1_id', type=int)
        bug2_id = request.form.get('bug2_id', type=int)
        tournament_id = request.form.get('tournament_id', type=int)
        match_id = request.form.get('match_id', type=int)
        
        if not bug1_id or not bug2_id:
            flash('Please select two bugs', 'danger')
            return redirect(url_for('battles.new_battle'))
        
        if bug1_id == bug2_id:
            flash('A bug cannot battle itself!', 'warning')
            return redirect(url_for('battles.new_battle'))
        
        bug1 = Bug.query.get_or_404(bug1_id)
        bug2 = Bug.query.get_or_404(bug2_id)

        # Simulate the battle, optionally linking it to a tournament/round
        battle = simulate_battle(bug1, bug2, tournament_id=tournament_id if tournament_id else None, round_number=0)

        # If this POST was started from a TournamentMatch, update the match row
        if match_id:
            try:
                tm = TournamentMatch.query.get(match_id)
                if tm:
                    tm.battle_id = battle.id
                    tm.winner_id = battle.winner_id
                    tm.completed_at = battle.battle_date if getattr(battle, 'battle_date', None) else None
                    db.session.add(tm)

                    # Propagate winner into next match slot if available
                    if tm.next_match_id and battle.winner_id:
                        next_m = TournamentMatch.query.get(tm.next_match_id)
                        if next_m:
                            # prefer filling bug1, then bug2
                            if not next_m.bug1_id:
                                next_m.bug1_id = battle.winner_id
                            elif not next_m.bug2_id:
                                next_m.bug2_id = battle.winner_id
                            db.session.add(next_m)

                    db.session.commit()
            except Exception:
                db.session.rollback()

        flash(f'Battle complete! {battle.winner.name if battle.winner else "Draw"} wins!', 'success')
        # If this was a tournament match, redirect back to the tournament page so the bracket refreshes
        if match_id:
            try:
                tm2 = TournamentMatch.query.get(match_id)
                if tm2 and tm2.tournament_id:
                    return redirect(url_for('tournaments.view_tournament', tournament_id=tm2.tournament_id))
            except Exception:
                pass
        return redirect(url_for('battles.view_battle', battle_id=battle.id))
    
    bugs = Bug.query.all()
    return render_template('create_battle.html', bugs=bugs)

@bp.route('/battle/random')
@login_required
def random_battle():
    import random
    
    bugs = Bug.query.all()
    
    if len(bugs) < 2:
        flash('Need at least 2 bugs to battle!', 'warning')
        return redirect(url_for('battles.list_battles'))
    
    bug1, bug2 = random.sample(bugs, 2)
    battle = simulate_battle(bug1, bug2)
    
    flash(f'Random battle! {battle.winner.name if battle.winner else "Draw"} wins!', 'success')
    return redirect(url_for('battles.view_battle', battle_id=battle.id))