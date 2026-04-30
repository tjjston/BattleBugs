from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user, login_required
from urllib.parse import urlparse
from app import db, limiter
from app.models import User
from sqlalchemy import func

bp = Blueprint('auth', __name__)


def _safe_next(next_url):
    """Return next_url only if it's a relative path (prevents open redirect)."""
    if next_url:
        parsed = urlparse(next_url)
        if not parsed.scheme and not parsed.netloc:
            return next_url
    return None


def _validate_password(password):
    """Return an error string or None if password is acceptable."""
    if not password or len(password) < 8:
        return 'Password must be at least 8 characters.'
    if len(password) > 256:
        return 'Password is too long.'
    return None


@bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('5 per minute')
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        password = request.form.get('password', '')

        if not username or len(username) < 3 or len(username) > 64:
            flash('Username must be between 3 and 64 characters.', 'danger')
            return redirect(url_for('auth.register'))

        pw_error = _validate_password(password)
        if pw_error:
            flash(pw_error, 'danger')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('auth.register'))

        if User.query.filter(func.lower(User.email) == email.lower()).first():
            flash('Email already registered', 'danger')
            return redirect(url_for('auth.register'))

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        remember = request.form.get('remember') == '1'

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user, remember=remember)
            next_page = _safe_next(request.args.get('next'))
            flash(f'Welcome back, {username}!', 'success')
            return redirect(next_page or url_for('main.index'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')


@bp.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def account_settings():
    """Self-service account settings: update email, password."""
    user = current_user
    if request.method == 'POST':
        new_email = (request.form.get('email') or '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if new_email and new_email.lower() != user.email.lower():
            if User.query.filter(func.lower(User.email) == new_email.lower()).first():
                flash('That email is already in use.', 'warning')
            else:
                user.email = new_email
                flash('Email updated.', 'success')

        if new_password:
            pw_error = _validate_password(new_password)
            if pw_error:
                flash(pw_error, 'danger')
            elif new_password != confirm_password:
                flash('Passwords do not match.', 'danger')
            else:
                user.set_password(new_password)
                flash('Password updated.', 'success')

        db.session.commit()
        return redirect(url_for('auth.account_settings'))

    return render_template('account_settings.html', user=user)
