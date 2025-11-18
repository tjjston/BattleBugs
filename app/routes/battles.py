from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from app import db
from app.models import Bug, Battle
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
        
        if not bug1_id or not bug2_id:
            flash('Please select two bugs', 'danger')
            return redirect(url_for('battles.new_battle'))
        
        if bug1_id == bug2_id:
            flash('A bug cannot battle itself!', 'warning')
            return redirect(url_for('battles.new_battle'))
        
        bug1 = Bug.query.get_or_404(bug1_id)
        bug2 = Bug.query.get_or_404(bug2_id)
        
        # Simulate the battle
        battle = simulate_battle(bug1, bug2)
        
        flash(f'Battle complete! {battle.winner.name if battle.winner else "Draw"} wins!', 'success')
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