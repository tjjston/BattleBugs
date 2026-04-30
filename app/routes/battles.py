from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import Bug, Battle, TournamentMatch, Tournament, Season, BugAchievement
from app.services.battle_engine import simulate_battle, calculate_battle_stats, visible_win_summary

bp = Blueprint('battles', __name__)

@bp.route('/battles')
def list_battles():
    page = request.args.get('page', 1, type=int)
    battles = Battle.query.order_by(Battle.battle_date.desc())\
        .paginate(page=page, per_page=10, error_out=False)
    
    return render_template('battle_list.html', battles=battles)

@bp.route('/battle/<int:battle_id>')
def view_battle(battle_id):
    battle = db.get_or_404(Battle, battle_id)
    battle_stats = calculate_battle_stats(battle.bug1, battle.bug2)
    summary = visible_win_summary(battle)
    return render_template('battle_view.html', battle=battle, battle_stats=battle_stats, win_summary=summary)

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
        
        bug1 = db.get_or_404(Bug, bug1_id)
        bug2 = db.get_or_404(Bug, bug2_id)

        # Simulate the battle, optionally linking it to a tournament/round
        battle = simulate_battle(bug1, bug2, tournament_id=tournament_id if tournament_id else None, round_number=0)

        # If this POST was started from a TournamentMatch, update the match row
        if match_id:
            try:
                tm = db.session.get(TournamentMatch, match_id)
                if tm:
                    # Verify match belongs to the supplied tournament
                    if tournament_id and tm.tournament_id != tournament_id:
                        flash('Match does not belong to the specified tournament.', 'danger')
                        return redirect(url_for('battles.new_battle'))
                    # Prevent overwriting an already-completed match
                    if tm.winner_id is not None:
                        flash('This tournament match has already been resolved.', 'warning')
                        return redirect(url_for('tournaments.view_tournament', tournament_id=tm.tournament_id))
                    tm.battle_id = battle.id
                    tm.winner_id = battle.winner_id
                    tm.completed_at = battle.battle_date if getattr(battle, 'battle_date', None) else None
                    db.session.add(tm)

                    # Propagate winner into next match slot if available
                    if tm.next_match_id and battle.winner_id:
                        next_m = db.session.get(TournamentMatch, tm.next_match_id)
                        if next_m:
                            # prefer filling bug1, then bug2
                            if not next_m.bug1_id:
                                next_m.bug1_id = battle.winner_id
                            elif not next_m.bug2_id:
                                next_m.bug2_id = battle.winner_id
                            db.session.add(next_m)

                    db.session.commit()

                    # Auto-complete tournament when all matches have a winner
                    if tm.tournament_id:
                        _maybe_complete_tournament(tm.tournament_id)
            except Exception:
                db.session.rollback()

        flash(f'Battle complete! {battle.winner.name if battle.winner else "Draw"} wins!', 'success')
        user_won = battle.winner and battle.winner.user_id == current_user.id
        # If this was a tournament match, redirect back to the tournament page so the bracket refreshes
        if match_id:
            try:
                tm2 = db.session.get(TournamentMatch, match_id)
                if tm2 and tm2.tournament_id:
                    tournament = db.session.get(Tournament, tm2.tournament_id)
                    tournament_complete = (tournament and tournament.status == 'completed'
                                          and battle.winner_id == tournament.winner_id)
                    if tournament_complete and user_won:
                        return redirect(url_for('tournaments.view_tournament',
                                                tournament_id=tm2.tournament_id,
                                                _celebrate='win'))
                    return redirect(url_for('tournaments.view_tournament', tournament_id=tm2.tournament_id))
            except Exception:
                pass
        kw = {'_celebrate': 'win'} if user_won else {}
        return redirect(url_for('battles.view_battle', battle_id=battle.id, **kw))
    
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


def _maybe_complete_tournament(tournament_id: int) -> None:
    """Auto-complete a tournament when all its TournamentMatch rows have a winner."""
    try:
        tournament = db.session.get(Tournament, tournament_id)
        if not tournament or tournament.status == 'completed':
            return

        matches = TournamentMatch.query.filter_by(tournament_id=tournament_id).all()
        if not matches:
            return
        if any(m.winner_id is None for m in matches):
            return  # still unresolved matches

        # Final match: highest round number, lowest match number
        final = max(matches, key=lambda m: (m.round_number, -m.match_number))
        if not final.winner_id:
            return

        tournament.winner_id = final.winner_id
        tournament.status = 'completed'

        # Award season champion achievement and retire all participants if this is a season playoff
        season = Season.query.filter_by(tournament_id=tournament_id).first()
        if season:
            season.phase = 'completed'
            winner_bug = db.session.get(Bug, final.winner_id)
            if winner_bug:
                existing = BugAchievement.query.filter_by(
                    bug_id=winner_bug.id, achievement_type='season_champion'
                ).first()
                if not existing:
                    from app.services.achievements import award_achievement
                    award_achievement(
                        winner_bug,
                        'season_champion',
                        'Season Champion',
                        '🏆',
                        f'Won the season-ending playoff tournament.',
                        rarity='legendary',
                    )
                    if winner_bug.owner:
                        winner_bug.owner.tournaments_won = (winner_bug.owner.tournaments_won or 0) + 1
            from app.services.job_queue import _retire_season_participants
            _retire_season_participants(season)

        db.session.commit()
    except Exception:
        db.session.rollback()
