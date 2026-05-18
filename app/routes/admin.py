"""
Admin Dashboard Routes
Access to secret bug stats, xfactors, matchup predictions
"""

from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Bug, Battle, Tournament, User, Job, ClassificationFlag, Notification, SystemSetting, RejectedSubmission
from app.services.permission_system import (
    require_role, UserRole, AdminBugAnalyzer, AdminUserManager,
    can_view_secrets
)
from app.services.tournament_system import TournamentManager
import sqlalchemy as sa
from sqlalchemy import text, func

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
    pending_classification_flags = ClassificationFlag.query.filter_by(status='pending').count()
    pending_rejected_count = RejectedSubmission.query.filter_by(status='pending').count()

    return render_template('admin/dashboard.html',
                         total_bugs=total_bugs,
                         total_users=total_users,
                         total_battles=total_battles,
                         total_tournaments=total_tournaments,
                         tier_dist=tier_dist,
                         recent_bugs=recent_bugs,
                         recent_battles=recent_battles,
                         pending_apps=pending_apps,
                         flagged_bugs=flagged_bugs,
                         pending_classification_flags=pending_classification_flags,
                         pending_rejected_count=pending_rejected_count)


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


@bp.route('/user/<int:user_id>')
@login_required
@require_role(UserRole.ADMIN)
def user_profile(user_id):
    """View detailed user profile and stats"""
    user = User.query.get_or_404(user_id)
    user_stats = AdminUserManager.get_user_stats(user)
    return render_template('admin/user_profile.html', user=user, stats=user_stats)


@bp.route('/user/<int:user_id>/update', methods=['POST'])
@login_required
@require_role(UserRole.ADMIN)
def update_user(user_id):
    """Admin user editor. Handles role, ELO, ban, and (for ADMIN/OWNER) free
    rename of username + email — no validation cooldowns, no rate limit, just
    a uniqueness check. Role assignment still enforces Owner-only promotions
    via AdminUserManager.
    """
    user = User.query.get_or_404(user_id)

    new_role_name = request.form.get('role')
    new_elo = request.form.get('elo')
    is_banned = True if request.form.get('is_banned') == '1' else False
    new_username = (request.form.get('username') or '').strip()
    new_email = (request.form.get('email') or '').strip()

    try:
        if new_role_name and new_role_name != user.role:
            AdminUserManager.assign_role(user, UserRole[new_role_name], current_user)

        if new_elo is not None and new_elo != '':
            try:
                user.elo = int(new_elo)
            except ValueError:
                flash('Invalid ELO value; not changed.', 'warning')

        # Username rename — free for admins/owners. Validation is intentionally
        # only "must not collide". No length / character / cooldown rules so
        # admins can fix typos, ban-evade rotations, etc. without ceremony.
        if new_username and new_username != user.username:
            collision = User.query.filter(
                func.lower(User.username) == new_username.lower(),
                User.id != user.id,
            ).first()
            if collision:
                flash(f'Username "{new_username}" is taken by another user.', 'warning')
            else:
                old = user.username
                user.username = new_username
                flash(f'Username changed: {old} → {new_username}.', 'success')

        if new_email and new_email.lower() != (user.email or '').lower():
            collision = User.query.filter(
                func.lower(User.email) == new_email.lower(),
                User.id != user.id,
            ).first()
            if collision:
                flash(f'Email "{new_email}" is in use by another user.', 'warning')
            else:
                user.email = new_email
                flash('Email updated.', 'success')

        user.is_banned = is_banned
        db.session.commit()
        flash('User updated', 'success')
    except PermissionError as e:
        flash(str(e), 'danger')

    return redirect(url_for('admin.user_profile', user_id=user.id))


@bp.route('/user/<int:user_id>/set-password', methods=['POST'])
@login_required
@require_role(UserRole.ADMIN)
def set_user_password(user_id):
    """Admin resets a user's password."""
    user = db.get_or_404(User, user_id)
    new_pw = request.form.get('new_password', '').strip()
    if len(new_pw) < 8:
        flash('Password must be at least 8 characters.', 'danger')
        return redirect(url_for('admin.user_profile', user_id=user.id))
    user.set_password(new_pw)
    db.session.commit()
    flash(f'Password for {user.username} has been reset.', 'success')
    return redirect(url_for('admin.user_profile', user_id=user.id))


@bp.route('/user/<int:user_id>/assign-role', methods=['POST'])
@login_required
@require_role(UserRole.OWNER)
def assign_user_role(user_id):
    """Assign a role to a user (owner only)"""
    user = User.query.get_or_404(user_id)
    new_role_name = request.form.get('role')
    
    try:
        new_role = UserRole[new_role_name]
        # Prevent owner from accidentally demoting themselves
        if user.id == current_user.id:
            current_role = UserRole[current_user.role]
            if new_role < current_role:
                flash('Refusing to demote the currently logged-in OWNER. Use another OWNER account to change roles.', 'danger')
                return redirect(url_for('admin.manage_users'))
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
    # Sorting and pagination
    sort = request.args.get('sort', 'xfactor')  # xfactor|wins|losses
    order = request.args.get('order', 'desc')   # asc|desc
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)

    q = Bug.query.filter(Bug.xfactor != 0)
    if sort == 'wins':
        sort_col = Bug.wins
    elif sort == 'losses':
        sort_col = Bug.losses
    else:
        sort_col = Bug.xfactor
    q = q.order_by(sort_col.asc() if order == 'asc' else sort_col.desc())

    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    bugs = pagination.items

    # Calculate statistics from full dataset (without pagination)
    all_xfactors = [b.xfactor for b in Bug.query.filter(Bug.xfactor != 0).all()]
    if all_xfactors:
        avg_xfactor = sum(all_xfactors) / len(all_xfactors)
        max_xfactor = max(all_xfactors)
        min_xfactor = min(all_xfactors)
        positive = sum(1 for x in all_xfactors if x > 0)
        negative = sum(1 for x in all_xfactors if x < 0)
    else:
        avg_xfactor = max_xfactor = min_xfactor = positive = negative = 0

    stats = {
        'average': round(avg_xfactor, 2) if all_xfactors else 0,
        'max': round(max_xfactor, 2) if all_xfactors else 0,
        'min': round(min_xfactor, 2) if all_xfactors else 0,
        'positive_count': positive,
        'negative_count': negative,
        'total_count': len(all_xfactors)
    }

    return render_template('admin/xfactor_insights.html', bugs=bugs, stats=stats,
                           pagination=pagination, sort=sort, order=order, per_page=per_page)


@bp.route('/db-explorer', methods=['GET', 'POST'])
@login_required
@require_role(UserRole.ADMIN)
def db_explorer():
    """Simple DB explorer for admins: preview tables and run SQL queries.

    NOTE: This endpoint allows running arbitrary SQL as the application user.
    It's admin-only and intended for development/ops. Use with caution.
    """
    if not current_app.config.get('ENABLE_DB_EXPLORER', False):
        flash('DB explorer is disabled. Set ENABLE_DB_EXPLORER=true to enable it.', 'warning')
        return redirect(url_for('admin.dashboard'))

    inspector = sa.inspect(db.engine)
    tables = inspector.get_table_names()

    selected_table = request.args.get('table')
    columns = []
    rows = []
    message = None

    # Running raw SQL (POST) or preview a table (GET with ?table=)
    if request.method == 'POST':
        sql = request.form.get('sql', '').strip()
        if not sql:
            message = 'No SQL provided.'
        else:
            try:
                # Use text() for safety and to get result metadata
                lowered = sql.lower().lstrip()
                is_read = lowered.startswith('select') or lowered.startswith('pragma')
                if not is_read and not current_app.config.get('DB_EXPLORER_ALLOW_WRITES', False):
                    message = 'Write SQL is disabled. Set DB_EXPLORER_ALLOW_WRITES=true to allow it.'
                    return render_template('admin/db_explorer.html', tables=tables, selected_table=selected_table,
                                           columns=columns, rows=rows, message=message)

                stmt = text(sql)
                res = db.session.execute(stmt)
                # If query returns rows, fetch them (limit client-side)
                if getattr(res, 'returns_rows', False):
                    columns = res.keys()
                    rows = res.fetchmany(200)
                else:
                    db.session.commit()
                    message = f'Affected rows: {res.rowcount}'
            except Exception as e:
                message = f'Error executing SQL: {e}'
    elif selected_table:
        # Preview selected table
        try:
            stmt = text(f'SELECT * FROM "{selected_table}" LIMIT 200')
            res = db.session.execute(stmt)
            columns = res.keys()
            rows = res.fetchall()
        except Exception as e:
            message = f'Error previewing table {selected_table}: {e}'

    return render_template('admin/db_explorer.html', tables=tables, selected_table=selected_table,
                           columns=columns, rows=rows, message=message)


@bp.route('/moderation')
@login_required
@require_role(UserRole.MODERATOR)
def moderation_queue():
    """Unified moderation queue: flagged bugs, pending tournament apps, and flagged users."""
    # Flagged bugs awaiting review
    flagged_bugs = Bug.query.filter_by(requires_manual_review=True).order_by(Bug.submission_date.desc()).all()

    # Pending tournament applications
    from app.models import TournamentApplication
    pending_apps = TournamentApplication.query.filter_by(status='pending') \
        .order_by(TournamentApplication.applied_at.desc()).all()

    # Users with warnings or banned
    flagged_users = User.query.filter(sa.or_(User.warnings > 0, User.is_banned == True)) \
        .order_by(User.created_at.desc()).all()

    return render_template('admin/moderation_queue.html',
                           flagged_bugs=flagged_bugs,
                           pending_apps=pending_apps,
                           flagged_users=flagged_users)


@bp.route('/battle/<int:battle_id>/reveal-secrets')
@login_required
@require_role(UserRole.ADMIN)
def reveal_battle_secrets(battle_id):
    """Reveal secret factors that influenced a battle"""
    from app.services.battle_engine import reveal_xfactor_secrets
    
    battle = Battle.query.get_or_404(battle_id)
    secrets = reveal_xfactor_secrets(battle)
    
    return render_template('admin/battle_secrets.html', battle=battle, secrets=secrets)


@bp.route('/jobs')
@login_required
@require_role(UserRole.ADMIN)
def jobs():
    status = request.args.get('status')
    query = Job.query
    if status:
        query = query.filter_by(status=status)
    jobs = query.order_by(Job.created_at.desc()).limit(100).all()
    return render_template('admin/jobs.html', jobs=jobs, status=status)


@bp.route('/jobs/<int:job_id>/retry', methods=['POST'])
@login_required
@require_role(UserRole.ADMIN)
def retry_job(job_id):
    from app.services.job_queue import retry_job as retry_background_job

    retry_background_job(job_id)
    flash('Job queued for retry.', 'success')
    return redirect(url_for('admin.jobs'))


@bp.route('/classification-flags')
@login_required
@require_role(UserRole.MODERATOR)
def classification_flags():
    """List all pending classification dispute flags."""
    status_filter = request.args.get('status', 'pending')
    flags = ClassificationFlag.query\
        .filter_by(status=status_filter)\
        .order_by(ClassificationFlag.created_at.asc())\
        .all()
    return render_template(
        'admin/classification_flags.html',
        flags=flags,
        status_filter=status_filter,
    )


@bp.route('/classification-flags/<int:flag_id>/dismiss', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def dismiss_classification_flag(flag_id):
    """Mark a classification dispute as dismissed (classification stands)."""
    from datetime import datetime as _dt
    flag = db.get_or_404(ClassificationFlag, flag_id)
    flag.status = 'dismissed'
    flag.reviewer_id = current_user.id
    flag.reviewer_notes = (request.form.get('notes') or '').strip() or None
    flag.reviewed_at = datetime.now(timezone.utc)

    user_message = (request.form.get('user_message') or '').strip()
    if user_message:
        notif = Notification(
            user_id=flag.flagging_user_id,
            message=f'Your classification dispute for "{flag.bug.nickname}" was reviewed: {user_message}',
            link_url=f'/bug/{flag.bug_id}',
        )
        db.session.add(notif)

    db.session.commit()
    flash('Flag dismissed — original classification stands.', 'info')
    return redirect(url_for('admin.classification_flags'))


@bp.route('/classification-flags/<int:flag_id>/correct', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def correct_from_flag(flag_id):
    """Apply species correction from a classification flag, update bug fields, and notify the user."""
    from datetime import datetime as _dt
    flag = db.get_or_404(ClassificationFlag, flag_id)
    bug = db.get_or_404(Bug, flag.bug_id)

    new_common = (request.form.get('common_name') or '').strip() or None
    new_scientific = (request.form.get('scientific_name') or '').strip() or None
    new_order = (request.form.get('order') or '').strip() or None
    new_family = (request.form.get('family') or '').strip() or None
    notes = (request.form.get('notes') or '').strip() or None
    user_message = (request.form.get('user_message') or '').strip()

    if new_common:
        bug.common_name = new_common
    if new_scientific:
        bug.scientific_name = new_scientific

    # Also update the linked Species record if one exists
    if bug.species_id and (new_common or new_scientific):
        from app.models import Species
        sp = db.session.get(Species, bug.species_id)
        if sp:
            if new_common:
                sp.common_name = new_common
            if new_scientific:
                sp.scientific_name = new_scientific
            if new_order:
                sp.order = new_order
            if new_family:
                sp.family = new_family

    flag.status = 'reviewed'
    flag.reviewer_id = current_user.id
    flag.reviewer_notes = notes
    flag.reviewed_at = datetime.now(timezone.utc)

    msg = user_message or f'Your dispute was accepted — "{bug.nickname}" has been reclassified as {new_common or new_scientific or "corrected"}.'
    notif = Notification(
        user_id=flag.flagging_user_id,
        message=msg,
        link_url=f'/bug/{flag.bug_id}',
    )
    db.session.add(notif)
    db.session.commit()
    flash(f'Classification updated for {bug.nickname} and user notified.', 'success')
    return redirect(url_for('admin.classification_flags'))


@bp.route('/llm-test', methods=['POST'])
@login_required
@require_role(UserRole.ADMIN)
def llm_test():
    """Fire a minimal prompt at the currently-configured LLM and return the result.

    Accepts optional JSON body: {"provider": "ollama"|"anthropic"|"openai", "task": "quick_tasks"}
    Used by the settings page to verify the connection is live before saving.
    """
    import time
    from app.services.llm_manager import LLMService, LLMModel, LLMConfig

    body = request.get_json(silent=True) or {}
    task = body.get('task', 'quick_tasks')
    provider_override = body.get('provider')

    model = None
    if provider_override == 'anthropic':
        model = LLMModel.CLAUDE_SONNET_4
    elif provider_override == 'openai':
        model = LLMModel.GPT_4
    elif provider_override == 'deepseek':
        model = LLMModel.DEEPSEEK_V4_FLASH
    elif provider_override == 'ollama':
        model = LLMConfig.TASK_MODELS.get(task, LLMConfig.DEFAULT_MODEL)
    else:
        model = LLMConfig.get_model_for_task(task)

    test_prompt = "Reply with only the number 42 and nothing else."
    llm = LLMService()
    start = time.monotonic()
    try:
        response = llm.generate(test_prompt, model=model, max_tokens=32, temperature=0)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return jsonify({
            'ok': True,
            'response': response.strip(),
            'model': model.name,
            'provider': model.provider,
            'elapsed_ms': elapsed_ms,
        })
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return jsonify({
            'ok': False,
            'error': str(exc),
            'model': model.name if model else None,
            'provider': model.provider if model else None,
            'elapsed_ms': elapsed_ms,
        }), 502


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
@require_role(UserRole.ADMIN)
def system_settings():
    """Admin system settings: LLM provider toggle, classifier toggle, URLs."""
    from app.services.llm_manager import LLMModel

    if request.method == 'POST':
        keys = [
            'llm_provider',
            'llm_model_battle_narrative', 'llm_model_stat_generation',
            'llm_model_vision_analysis', 'llm_model_species_identification',
            'llm_model_quick_tasks',
            'classifier_enabled', 'classifier_required',
            'ollama_url', 'classifier_url',
        ]
        for k in keys:
            v = request.form.get(k, '').strip()
            if v:
                SystemSetting.set(k, v, user_id=current_user.id)
            else:
                # Empty value → delete override so app config takes over
                row = db.session.get(SystemSetting, k)
                if row:
                    db.session.delete(row)
        db.session.commit()
        flash('Settings saved.', 'success')
        return redirect(url_for('admin.system_settings'))

    settings = {row.key: row.value for row in SystemSetting.query.all()}
    llm_models = [m.name for m in LLMModel]
    from app.services.news_service import _read_cache as _news_read_cache
    cached_text, cached_at = _news_read_cache()
    import time as _time
    news_age_min = int((_time.time() - cached_at) / 60) if cached_at else None
    return render_template('admin/settings.html', settings=settings, llm_models=llm_models,
                           news_briefing=cached_text, news_age_min=news_age_min)


@bp.route('/news/refresh', methods=['POST'])
@login_required
@require_role(UserRole.ADMIN)
def refresh_news():
    from app.services.news_service import invalidate_news_cache
    invalidate_news_cache()
    flash('News cache cleared — briefing will regenerate on next homepage load.', 'success')
    return redirect(url_for('admin.system_settings'))


# ── Bug management ────────────────────────────────────────────────────────────

@bp.route('/bugs')
@login_required
@require_role(UserRole.MODERATOR)
def bug_list():
    """Searchable bug list for admin editing."""
    q = request.args.get('q', '').strip()
    tier = request.args.get('tier', '')
    condition = request.args.get('condition', '')
    page = request.args.get('page', 1, type=int)

    query = Bug.query
    if q:
        like = f'%{q}%'
        query = query.filter(
            sa.or_(Bug.nickname.ilike(like), Bug.common_name.ilike(like),
                   Bug.scientific_name.ilike(like))
        )
    if tier:
        query = query.filter_by(tier=tier)
    if condition:
        query = query.filter_by(condition=condition)
    pagination = query.order_by(Bug.submission_date.desc()).paginate(page=page, per_page=30, error_out=False)
    return render_template('admin/bug_list.html', pagination=pagination, q=q, tier=tier, condition=condition)


@bp.route('/bug/<int:bug_id>/edit', methods=['GET', 'POST'])
@login_required
@require_role(UserRole.MODERATOR)
def edit_bug(bug_id):
    """Edit a bug's stats, condition, tier, and classification."""
    bug = db.get_or_404(Bug, bug_id)

    if request.method == 'POST':
        action = request.form.get('action', 'save')

        if action == 'regenerate_stats':
            try:
                from app.services.tier_system import TierSystem
                TierSystem.regenerate_stats_for_bug(bug)
                db.session.commit()
                flash('Stats regenerated via LLM.', 'success')
            except Exception as exc:
                flash(f'Stat regeneration failed: {exc}', 'danger')
            return redirect(url_for('admin.edit_bug', bug_id=bug.id))

        # Apply manual edits
        def _int(key, default):
            try:
                return int(request.form.get(key, default))
            except (ValueError, TypeError):
                return default

        def _float(key, default):
            try:
                return float(request.form.get(key, default))
            except (ValueError, TypeError):
                return default

        bug.nickname = request.form.get('nickname', bug.nickname).strip() or bug.nickname
        bug.common_name = request.form.get('common_name', '').strip() or None
        bug.scientific_name = request.form.get('scientific_name', '').strip() or None
        bug.tier = request.form.get('tier', bug.tier)
        bug.condition = request.form.get('condition', bug.condition)
        bug.condition_notes = request.form.get('condition_notes', '').strip() or None
        bug.attack = _int('attack', bug.attack)
        bug.defense = _int('defense', bug.defense)
        bug.speed = _int('speed', bug.speed)
        bug.lethality = _int('lethality', bug.lethality or 50)
        bug.grip = _int('grip', bug.grip or 50)
        bug.cunning = _int('cunning', bug.cunning or 50)
        bug.xfactor = _float('xfactor', bug.xfactor or 0.0)
        bug.xfactor_reason = request.form.get('xfactor_reason', '').strip() or bug.xfactor_reason
        bug.is_zombug = request.form.get('is_zombug') == '1'
        bug.is_retired = request.form.get('is_retired') == '1'
        bug.requires_manual_review = request.form.get('requires_manual_review') == '1'
        bug.flair = request.form.get('flair', '').strip() or None
        notes = request.form.get('admin_notes', '').strip()
        if notes:
            bug.review_notes = notes

        db.session.commit()
        flash(f'{bug.nickname} updated.', 'success')
        return redirect(url_for('admin.edit_bug', bug_id=bug.id))

    return render_template('admin/edit_bug.html', bug=bug)


# ── Tournament management ─────────────────────────────────────────────────────

@bp.route('/tournaments')
@login_required
@require_role(UserRole.MODERATOR)
def tournament_list():
    """List all tournaments for admin management."""
    status = request.args.get('status', '')
    query = Tournament.query
    if status:
        query = query.filter_by(status=status)
    tournaments = query.order_by(Tournament.created_at.desc()).all()
    return render_template('admin/tournament_list.html', tournaments=tournaments, status=status)


@bp.route('/tournament/<int:tournament_id>/edit', methods=['GET', 'POST'])
@login_required
@require_role(UserRole.MODERATOR)
def edit_tournament(tournament_id):
    """Edit a tournament's details and status."""
    from datetime import datetime as _dt
    tournament = db.get_or_404(Tournament, tournament_id)

    if request.method == 'POST':
        tournament.name = request.form.get('name', tournament.name).strip() or tournament.name
        # Capture status BEFORE assignment so we can detect a flip into 'active'
        # — if it's the first time the tournament becomes active, we auto-fire
        # the bracket generator. Without this, an admin could set status=active
        # via the edit form and end up with an active tournament with 0 matches.
        _prev_status = tournament.status
        tournament.status = request.form.get('status', tournament.status)
        tournament.tier = request.form.get('tier', '').strip() or None
        tournament.max_participants = request.form.get('max_participants', type=int) or tournament.max_participants
        tournament.allow_tier_above = request.form.get('allow_tier_above') == '1'

        start_str = request.form.get('start_date', '').strip()
        end_str = request.form.get('end_date', '').strip()
        deadline_str = request.form.get('registration_deadline', '').strip()
        try:
            if start_str:
                tournament.start_date = _dt.fromisoformat(start_str)
            if end_str:
                tournament.end_date = _dt.fromisoformat(end_str)
            if deadline_str:
                tournament.registration_deadline = _dt.fromisoformat(deadline_str)
        except ValueError as exc:
            flash(f'Invalid date format: {exc}', 'danger')
            return redirect(url_for('admin.edit_tournament', tournament_id=tournament.id))

        tournament.format = request.form.get('format', tournament.format or 'single_elimination')
        tournament.submissions_per_user = request.form.get('submissions_per_user', type=int) or 2
        db.session.commit()

        # If the admin just promoted the tournament to 'active' and it has no
        # matches yet, generate the bracket now. Otherwise the user ends up
        # with an 'active' tournament and an empty bracket page.
        if (_prev_status != 'active' and tournament.status == 'active'
                and not tournament.matches.first()):
            try:
                from app.services.tournament_system import TournamentManager
                matches = TournamentManager.generate_bracket(tournament.id)
                flash(f'Bracket generated: {len(matches)} round-1 matches.', 'success')
            except Exception as exc:
                flash(f'Tournament saved as active, but bracket generation failed: {exc}', 'warning')

        flash(f'Tournament "{tournament.name}" updated.', 'success')
        return redirect(url_for('admin.edit_tournament', tournament_id=tournament.id))

    from app.models import TournamentApplication as _TA, Bug as _Bug
    apps = _TA.query.filter_by(tournament_id=tournament_id).order_by(_TA.seed_number).all()
    enrolled_bug_ids = {a.bug_id for a in apps}
    tournament_battles = tournament.battles.order_by(Battle.round_number, Battle.id).all() \
        if hasattr(tournament, 'battles') else []
    # Bugs eligible to add: not retired, not already in this tournament
    tier_filter = request.args.get('tier_filter', '')
    bug_query = _Bug.query.filter(_Bug.id.notin_(enrolled_bug_ids), _Bug.is_retired == False)
    if tier_filter:
        bug_query = bug_query.filter(_Bug.tier == tier_filter)
    available_bugs = bug_query.order_by(_Bug.tier, _Bug.nickname).all()
    return render_template('admin/edit_tournament.html', tournament=tournament,
                           applications=apps, tournament_battles=tournament_battles,
                           available_bugs=available_bugs, tier_filter=tier_filter)


@bp.route('/tournament/<int:tournament_id>/add-bug', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def tournament_add_bug(tournament_id):
    """Admin-add a bug directly into a tournament (creates an approved application)."""
    from app.models import TournamentApplication, Bug as _Bug
    tournament = db.get_or_404(Tournament, tournament_id)
    bug_id = request.form.get('bug_id', type=int)
    if not bug_id:
        flash('Bug ID required.', 'danger')
        return redirect(url_for('admin.edit_tournament', tournament_id=tournament_id))

    bug = db.session.get(_Bug, bug_id)
    if not bug:
        flash(f'Bug #{bug_id} not found.', 'danger')
        return redirect(url_for('admin.edit_tournament', tournament_id=tournament_id))

    existing = TournamentApplication.query.filter_by(
        tournament_id=tournament_id, bug_id=bug_id).first()
    if existing:
        flash(f'{bug.nickname} is already in this tournament.', 'warning')
        return redirect(url_for('admin.edit_tournament', tournament_id=tournament_id))

    app = TournamentApplication(
        tournament_id=tournament_id, bug_id=bug_id,
        user_id=bug.user_id, status='approved',
    )
    db.session.add(app)
    db.session.commit()
    flash(f'{bug.nickname} added to tournament.', 'success')
    return redirect(url_for('admin.edit_tournament', tournament_id=tournament_id))


@bp.route('/tournament/<int:tournament_id>/remove-bug/<int:app_id>', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def tournament_remove_bug(tournament_id, app_id):
    """Remove a bug application from a tournament."""
    from app.models import TournamentApplication
    app = db.get_or_404(TournamentApplication, app_id)
    name = app.bug.nickname if app.bug else f'#{app.bug_id}'
    db.session.delete(app)
    db.session.commit()
    flash(f'{name} removed from tournament.', 'info')
    return redirect(url_for('admin.edit_tournament', tournament_id=tournament_id))


@bp.route('/tournament/<int:tournament_id>/set-seed/<int:app_id>', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def tournament_set_seed(tournament_id, app_id):
    """Manually override a bug's seed number."""
    from app.models import TournamentApplication
    app = db.get_or_404(TournamentApplication, app_id)
    seed = request.form.get('seed', type=int)
    app.seed_number = seed
    db.session.commit()
    flash('Seed updated.', 'success')
    return redirect(url_for('admin.edit_tournament', tournament_id=tournament_id))


@bp.route('/battle/<int:battle_id>/overturn', methods=['POST'])
@login_required
@require_role(UserRole.ADMIN)
def overturn_battle(battle_id):
    """Override a battle result — swap winner/loser and adjust win/loss counts."""
    battle = db.get_or_404(Battle, battle_id)
    new_winner_id = request.form.get('winner_id', type=int)
    if new_winner_id not in (battle.bug1_id, battle.bug2_id):
        flash('Winner must be one of the two combatants.', 'danger')
        return redirect(url_for('admin.edit_tournament',
                                tournament_id=battle.tournament_id) if battle.tournament_id
                        else url_for('admin.dashboard'))

    old_winner_id = battle.winner_id
    if old_winner_id == new_winner_id:
        flash('No change — same winner selected.', 'info')
        return redirect(url_for('battles.view_battle', battle_id=battle_id))

    from app.models import Bug as _Bug
    if old_winner_id:
        loser = db.session.get(_Bug, old_winner_id)
        if loser:
            loser.wins = max(0, (loser.wins or 0) - 1)
            loser.losses = (loser.losses or 0) + 1
    new_loser_id = battle.bug1_id if new_winner_id == battle.bug2_id else battle.bug2_id
    old_loser = db.session.get(_Bug, new_loser_id)
    if old_loser:
        old_loser.losses = max(0, (old_loser.losses or 0) - 1)
        old_loser.wins = (old_loser.wins or 0) + 1
    new_winner = db.session.get(_Bug, new_winner_id)
    if new_winner:
        new_winner.wins = (new_winner.wins or 0) + 1
        new_winner.losses = max(0, (new_winner.losses or 0) - 1)

    battle.winner_id = new_winner_id
    db.session.commit()
    flash(f'Battle result overturned — {new_winner.nickname if new_winner else new_winner_id} is now the winner.', 'success')
    return redirect(url_for('battles.view_battle', battle_id=battle_id))


@bp.route('/tournament/<int:tournament_id>/delete', methods=['POST'])
@login_required
@require_role(UserRole.ADMIN)
def delete_tournament(tournament_id):
    """Delete a tournament (admin only)."""
    tournament = db.get_or_404(Tournament, tournament_id)
    name = tournament.name
    db.session.delete(tournament)
    db.session.commit()
    flash(f'Tournament "{name}" deleted.', 'warning')
    return redirect(url_for('admin.tournament_list'))


# Context processor to make admin checks available in templates
@bp.app_context_processor
def inject_admin_helpers():
    return {
        'can_view_secrets': lambda: can_view_secrets(current_user),
        'is_admin': lambda: current_user.is_authenticated and current_user.role in ['ADMIN', 'OWNER'],
        'is_moderator': lambda: current_user.is_authenticated and current_user.role in ['MODERATOR', 'ADMIN', 'OWNER'],
        'is_owner': lambda: current_user.is_authenticated and current_user.role == 'OWNER'
    }
