from flask import Blueprint, render_template, redirect, url_for, flash, request, Response, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Bug, Battle, TournamentMatch, Tournament
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


@bp.route('/battle/<int:battle_id>/narrative/stream')
@login_required
def stream_battle_narrative(battle_id):
    """Server-Sent Events: stream a fresh battle narrative token by token.

    Used by the "Re-narrate live" button on the battle view. Replaces the
    stored narrative on the battle record when the stream ends so the
    next page load shows the new one.
    """
    battle = db.get_or_404(Battle, battle_id)
    bug1, bug2 = battle.bug1, battle.bug2
    winner = bug1 if battle.winner_id == bug1.id else bug2

    from app.services.visual_lore_generator import _build_battle_prompt  # see helper below
    prompt = _build_battle_prompt(bug1, bug2, winner, venue=None)
    app = current_app._get_current_object()

    def _stream():
        from app.services.llm_manager import LLMService
        buf = []
        try:
            llm = LLMService()
            for chunk in llm.generate_stream(prompt, task='battle_narrative',
                                             max_tokens=900, temperature=0.85):
                if not chunk:
                    continue
                buf.append(chunk)
                # SSE frame: each "data:" line is one event payload. Replace
                # newlines so the SSE format isn't broken by line content.
                safe = chunk.replace('\r', '').replace('\n', '\\n')
                yield f"data: {safe}\n\n"
            full = "".join(buf).strip()
            if full:
                with app.app_context():
                    fresh = db.session.get(Battle, battle_id)
                    if fresh is not None:
                        fresh.narrative = full
                        db.session.commit()
            yield "event: done\ndata: end\n\n"
        except Exception as exc:
            app.logger.warning("narrative stream failed: %s", exc)
            yield f"event: error\ndata: {exc}\n\n"

    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'X-Accel-Buffering': 'no',          # disable nginx buffering if present
        'Connection': 'keep-alive',
    }
    return Response(_stream(), headers=headers)

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

        db.session.commit()
    except Exception:
        db.session.rollback()
