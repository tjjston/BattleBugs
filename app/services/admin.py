"""
Admin Dashboard Routes
Access to secret bug stats, xfactors, matchup predictions
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import Bug, Battle, Tournament, User
from app.services.permission_system import (
    require_role, UserRole, AdminBugAnalyzer, AdminUserManager,
    can_view_secrets
)
from app.services.tournament_system import TournamentManager

bp = Blueprint('admin', __name__, url_prefix='/admin')


@bp.route('/dashboard')
@login_required
@require_role(UserRole.ADMIN)
def dashboard():
    """Main admin dashboard"""
    # Get statistics
    total_bugs = Bug.query.count()
    total_users = User.query.count()
    total_battles = Battle.query.count()
    total_tournaments = Tournament.query.count()
    
    # Get tier distribution
    tier_dist = AdminBugAnalyzer.get_tier_distribution()
    
    # Recent activity
    recent_bugs = Bug.query.order_by(Bug.submission_date.desc()).limit(5).all()
    recent_battles = Battle.query.order_by(Battle.battle_date.desc()).limit(5).all()
    
    # Pending applications
    from app.services.tournament_system import TournamentApplication
    pending_apps = TournamentApplication.query.filter_by(status='pending').count()
    
    # Flagged bugs
    flagged_bugs = Bug.query.filter_by(requires_manual_review=True).count()
    
    return render_template('admin/dashboard.html',
                         total_bugs=total_bugs,
                         total_users=total_users,
                         total_battles=total_battles,
                         total_tournaments=total_tournaments,
                         tier_dist=tier_dist,
                         recent_bugs=recent_bugs,
                         recent_battles=recent_battles,
                         pending_apps=pending_apps,
                         flagged_bugs=flagged_bugs)


@bp.route('/bug/<int:bug_id>/secrets')
@login_required
@require_role(UserRole.ADMIN)
def view_bug_secrets(bug_id):
    """View secret stats for a bug"""
    bug = Bug.query.get_or_404(bug_id)
    secrets = AdminBugAnalyzer.get_bug_secrets(bug)
    
    return render_template('admin/bug_secrets.html', bug=bug, secrets=secrets)


@bp.route('/api/bug/<int:bug_id>/secrets')
@login_required
@require_role(UserRole.ADMIN)
def api_bug_secrets(bug_id):
    """API endpoint for bug secrets"""
    bug = Bug.query.get_or_404(bug_id)
    secrets = AdminBugAnalyzer.get_bug_secrets(bug)
    
    return jsonify({
        'bug_id': bug_id,
        'nickname': bug.nickname,
        'secrets': secrets
    })


@bp.route('/matchup-predictor', methods=['GET', 'POST'])
@login_required
@require_role(UserRole.ADMIN)
def matchup_predictor():
    """Predict battle outcomes"""
    prediction = None
    bug1 = None
    bug2 = None
    
    if request.method == 'POST':
        bug1_id = request.form.get('bug1_id', type=int)
        bug2_id = request.form.get('bug2_id', type=int)
        
        if bug1_id and bug2_id:
            bug1 = Bug.query.get_or_404(bug1_id)
            bug2 = Bug.query.get_or_404(bug2_id)
            
            prediction = AdminBugAnalyzer.predict_battle_outcome(bug1, bug2)
    
    # Get all bugs for selection
    bugs = Bug.query.order_by(Bug.nickname).all()
    
    return render_template('admin/matchup_predictor.html',
                         bugs=bugs,
                         bug1=bug1,
                         bug2=bug2,
                         prediction=prediction)


@bp.route('/api/predict-matchup', methods=['POST'])
@login_required
@require_role(UserRole.ADMIN)
def api_predict_matchup():
    """API endpoint for matchup prediction"""
    data = request.get_json()
    bug1_id = data.get('bug1_id')
    bug2_id = data.get('bug2_id')
    
    if not bug1_id or not bug2_id:
        return jsonify({'error': 'Both bug IDs required'}), 400
    
    bug1 = Bug.query.get_or_404(bug1_id)
    bug2 = Bug.query.get_or_404(bug2_id)
    
    prediction = AdminBugAnalyzer.predict_battle_outcome(bug1, bug2)
    
    return jsonify({
        'bug1': {
            'id': bug1.id,
            'nickname': bug1.nickname,
            'win_chance': prediction['bug1_win_chance']
        },
        'bug2': {
            'id': bug2.id,
            'nickname': bug2.nickname,
            'win_chance': prediction['bug2_win_chance']
        },
        'expected_winner': {
            'id': prediction['expected_winner'].id,
            'nickname': prediction['expected_winner'].nickname
        },
        'factors': prediction['factors'],
        'confidence': prediction['confidence'],
        'power_breakdown': prediction['power_breakdown']
    })


@bp.route('/users')
@login_required
@require_role(UserRole.ADMIN)
def manage_users():
    """User management panel"""
    users = User.query.order_by(User.created_at.desc()).all()
    
    user_stats = {}
    for user in users:
        user_stats[user.id] = AdminUserManager.get_user_stats(user)
    
    return render_template('admin/manage_users.html',
                         users=users,
                         user_stats=user_stats)


@bp.route('/user/<int:user_id>/assign-role', methods=['POST'])
@login_required
@require_role(UserRole.OWNER)
def assign_user_role(user_id):
    """Assign a role to a user (owner only)"""
    user = User.query.get_or_404(user_id)
    new_role_name = request.form.get('role')
    
    try:
        new_role = UserRole[new_role_name]
        AdminUserManager.assign_role(user, new_role, current_user)
        flash(f'{user.username} is now a {new_role.name}', 'success')
    except (KeyError, PermissionError) as e:
        flash(str(e), 'danger')
    
    return redirect(url_for('admin.manage_users'))


@bp.route('/bugs/flagged')
@login_required
@require_role(UserRole.MODERATOR)
def flagged_bugs():
    """View bugs requiring manual review"""
    bugs = Bug.query.filter_by(requires_manual_review=True).order_by(Bug.submission_date.desc()).all()
    
    return render_template('admin/flagged_bugs.html', bugs=bugs)


@bp.route('/bug/<int:bug_id>/approve-review', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def approve_bug_review(bug_id):
    """Approve a flagged bug"""
    bug = Bug.query.get_or_404(bug_id)
    
    bug.requires_manual_review = False
    bug.is_verified = True
    bug.review_notes = request.form.get('notes', f'Approved by {current_user.username}')
    
    db.session.commit()
    
    flash(f'{bug.nickname} approved!', 'success')
    return redirect(url_for('admin.flagged_bugs'))


@bp.route('/tournaments/applications')
@login_required
@require_role(UserRole.MODERATOR)
def tournament_applications():
    """View pending tournament applications"""
    from app.services.tournament_system import TournamentApplication
    
    pending = TournamentApplication.query.filter_by(status='pending')\
        .order_by(TournamentApplication.applied_at.desc()).all()
    
    return render_template('admin/tournament_applications.html', applications=pending)


@bp.route('/tournament-application/<int:app_id>/approve', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def approve_tournament_application(app_id):
    """Approve a tournament application"""
    TournamentManager.approve_application(app_id, current_user.id)
    
    flash('Application approved!', 'success')
    return redirect(url_for('admin.tournament_applications'))


@bp.route('/xfactor-insights')
@login_required
@require_role(UserRole.ADMIN)
def xfactor_insights():
    """View xfactor distribution and insights"""
    # Get all bugs with xfactor data
    bugs = Bug.query.filter(Bug.xfactor != 0).order_by(Bug.xfactor.desc()).all()
    
    # Calculate statistics
    if bugs:
        xfactors = [bug.xfactor for bug in bugs]
        avg_xfactor = sum(xfactors) / len(xfactors)
        max_xfactor = max(xfactors)
        min_xfactor = min(xfactors)
        
        # Count positive vs negative
        positive = sum(1 for x in xfactors if x > 0)
        negative = sum(1 for x in xfactors if x < 0)
    else:
        avg_xfactor = max_xfactor = min_xfactor = positive = negative = 0
    
    stats = {
        'average': round(avg_xfactor, 2) if bugs else 0,
        'max': round(max_xfactor, 2) if bugs else 0,
        'min': round(min_xfactor, 2) if bugs else 0,
        'positive_count': positive,
        'negative_count': negative,
        'total_count': len(bugs)
    }
    
    return render_template('admin/xfactor_insights.html', bugs=bugs, stats=stats)


@bp.route('/battle/<int:battle_id>/reveal-secrets')
@login_required
@require_role(UserRole.ADMIN)
def reveal_battle_secrets(battle_id):
    """Reveal secret factors that influenced a battle"""
    from app.services.battle_engine import reveal_xfactor_secrets
    
    battle = Battle.query.get_or_404(battle_id)
    secrets = reveal_xfactor_secrets(battle)
    
    return render_template('admin/battle_secrets.html', battle=battle, secrets=secrets)


# Context processor to make admin checks available in templates
@bp.app_context_processor
def inject_admin_helpers():
    return {
        'can_view_secrets': lambda: can_view_secrets(current_user),
        'is_admin': lambda: current_user.is_authenticated and current_user.role in ['ADMIN', 'OWNER'],
        'is_moderator': lambda: current_user.is_authenticated and current_user.role in ['MODERATOR', 'ADMIN', 'OWNER']
    }