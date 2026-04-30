"""
Championship routes — MMA-style per-tier belt system.
"""
from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, session
from flask_login import login_required, current_user

from app import db
from app.models import (
    Bug, TierChampionship, TierRanking, TitleFight, TitleBid, ContenderCallout,
    CHAMPIONSHIP_TIERS, CONTENDER_MIN_BIDS,
)
from app.services.championship_service import (
    get_contenders, get_pfp_rankings, ensure_championships,
    place_bid, issue_callout, respond_callout, recalculate_tier_rankings,
    MIN_WINS_FOR_RANKING,
)

bp = Blueprint('championship', __name__, url_prefix='/championship')

TIER_LABELS = {
    'uber': 'Legendary (Uber)',
    'ou': 'Elite (OU)',
    'uu': 'Strong (UU)',
    'ru': 'Rising (RU)',
    'nu': 'Newcomer (NU)',
    'zu': 'Zero (ZU)',
}


def _tier_overview(tier: str) -> dict:
    champ = TierChampionship.query.filter_by(tier=tier).first()
    contenders = get_contenders(tier, limit=10)
    fight = TitleFight.query.filter(
        TitleFight.tier == tier,
        TitleFight.status.in_(['bidding', 'locked']),
    ).order_by(TitleFight.created_at.desc()).first()

    bids = {}
    if fight:
        for bid in fight.bids:
            bids[bid.bug_id] = bid

    return {
        'tier': tier,
        'label': TIER_LABELS.get(tier, tier.upper()),
        'championship': champ,
        'contenders': contenders,
        'fight': fight,
        'bids': bids,
        'min_bids': CONTENDER_MIN_BIDS,
    }


@bp.route('/')
def overview():
    ensure_championships()
    tiers = [_tier_overview(t) for t in CHAMPIONSHIP_TIERS]

    # Upcoming fight card: all active/scheduled fights ordered by date
    upcoming_fights = TitleFight.query.filter(
        TitleFight.status.in_(['bidding', 'locked'])
    ).order_by(TitleFight.scheduled_date.asc()).all()

    past_fights = TitleFight.query.filter(
        TitleFight.status == 'completed'
    ).order_by(TitleFight.scheduled_date.desc()).limit(6).all()

    return render_template('championship.html', tiers=tiers,
                           upcoming_fights=upcoming_fights,
                           past_fights=past_fights,
                           now=datetime.now(timezone.utc))


@bp.route('/<tier>')
def tier_detail(tier: str):
    if tier not in CHAMPIONSHIP_TIERS:
        abort(404)
    ensure_championships()
    data = _tier_overview(tier)

    # Fire belt celebration once per win for the owning user
    if not request.args.get('_celebrate') and current_user.is_authenticated:
        champ = data['championship']
        if champ and champ.champion and champ.champion.user_id == current_user.id and champ.won_date:
            won = champ.won_date
            if won.tzinfo is None:
                won = won.replace(tzinfo=timezone.utc)
            session_key = f'belt_celebrated_{champ.id}_{int(won.timestamp())}'
            if not session.get(session_key) and (datetime.now(timezone.utc) - won) < timedelta(hours=6):
                session[session_key] = True
                return redirect(url_for('championship.tier_detail', tier=tier, _celebrate='belt'))

    # Pending callouts involving user's bugs
    user_callouts = []
    if current_user.is_authenticated:
        user_bug_ids = [b.id for b in current_user.bugs if b.bug_track == 'mma' and b.tier == tier]
        if user_bug_ids:
            user_callouts = ContenderCallout.query.filter(
                ContenderCallout.tier == tier,
                ContenderCallout.status == 'pending',
                (ContenderCallout.challenger_bug_id.in_(user_bug_ids) |
                 ContenderCallout.target_bug_id.in_(user_bug_ids)),
            ).all()

    return render_template('championship_tier.html', data=data,
                           tier_labels=TIER_LABELS, user_callouts=user_callouts)


@bp.route('/bid', methods=['POST'])
@login_required
def submit_bid():
    fight_id = request.form.get('fight_id', type=int)
    bug_id = request.form.get('bug_id', type=int)
    amount = request.form.get('amount', type=int, default=0)

    if not fight_id or not bug_id:
        flash('Invalid request.', 'danger')
        return redirect(url_for('championship.overview'))

    bug = db.get_or_404(Bug, bug_id)
    if bug.user_id != current_user.id:
        abort(403)

    ok, msg = place_bid(fight_id, bug, current_user, amount)
    flash(msg, 'success' if ok else 'danger')

    fight = db.session.get(TitleFight, fight_id)
    return redirect(url_for('championship.tier_detail', tier=fight.tier) if fight else
                    url_for('championship.overview'))


@bp.route('/callout', methods=['POST'])
@login_required
def callout():
    challenger_id = request.form.get('challenger_id', type=int)
    target_id = request.form.get('target_id', type=int)

    if not challenger_id or not target_id:
        flash('Invalid callout.', 'danger')
        return redirect(url_for('championship.overview'))

    challenger = db.get_or_404(Bug, challenger_id)
    target = db.get_or_404(Bug, target_id)

    if challenger.user_id != current_user.id:
        abort(403)

    ok, msg = issue_callout(challenger, target)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('championship.tier_detail', tier=challenger.tier))


@bp.route('/callout/<int:callout_id>/respond', methods=['POST'])
@login_required
def respond_to_callout(callout_id: int):
    callout_obj = db.get_or_404(ContenderCallout, callout_id)

    if callout_obj.target.user_id != current_user.id:
        abort(403)

    accept = request.form.get('action') == 'accept'
    ok, msg = respond_callout(callout_id, accept)
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('championship.tier_detail', tier=callout_obj.tier))


@bp.route('/enter-mma/<int:bug_id>', methods=['POST'])
@login_required
def enter_mma(bug_id: int):
    """Enroll a bug (especially season-retired) into the MMA championship track."""
    bug = db.get_or_404(Bug, bug_id)
    if bug.user_id != current_user.id:
        abort(403)

    if bug.bug_track == 'mma':
        flash(f'{bug.nickname} is already in the MMA track.', 'info')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))

    if bug.bug_track == 'season' and not bug.is_retired:
        flash('Active season bugs cannot enter the MMA track until they retire from the season.', 'warning')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))

    # Enforce 2-per-tier active limit
    active_mma = Bug.query.filter(
        Bug.user_id == current_user.id,
        Bug.bug_track == 'mma',
        Bug.tier == bug.tier,
        Bug.is_retired == False,
    ).count()
    if active_mma >= 2:
        flash(f'You already have 2 active MMA bugs in the {(bug.tier or "").upper()} tier. '
              'Retire one to enter another.', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))

    bug.bug_track = 'mma'
    db.session.commit()

    # Re-run ranking for this tier now that a new bug has joined
    try:
        recalculate_tier_rankings(bug.tier)
    except Exception:
        pass

    flash(f'{bug.nickname} has entered the MMA championship track! '
          f'Earn {MIN_WINS_FOR_RANKING}+ wins to enter the contender rankings.', 'success')
    return redirect(url_for('bugs.view_bug', bug_id=bug_id))


@bp.route('/pfp')
def pfp():
    rankings = get_pfp_rankings(limit=30)
    return render_template('championship_pfp.html', rankings=rankings)
