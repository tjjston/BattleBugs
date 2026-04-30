"""
Playwright E2E test configuration.

Starts a live Flask server in a background thread against a fresh in-memory DB,
then tears it down after the session.  All tests receive a `base_url` fixture.

Run:
    pytest tests/e2e/ --headed          # show browser
    pytest tests/e2e/                   # headless (CI default)
    pytest tests/e2e/ -k test_login     # single test
"""

import threading
import time
import pytest

from app import create_app, db as _db
from app.models import User, Bug


# ── Server configuration ────────────────────────────────────────────────────

E2E_PORT = 5055


class E2EConfig:
    TESTING = True
    SECRET_KEY = 'e2e-test-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:////tmp/battlebugs_e2e.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    ENABLE_BACKGROUND_JOBS = False
    ENABLE_DB_EXPLORER = False
    DB_EXPLORER_ALLOW_WRITES = False
    UPLOAD_FOLDER = '/tmp/battlebugs-e2e-uploads'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    BUGS_PER_PAGE = 20
    BATTLES_PER_PAGE = 10
    SERVER_NAME = None


# ── Session-scoped fixtures ─────────────────────────────────────────────────

@pytest.fixture(scope='session')
def flask_app():
    import os, shutil
    # Clean any leftover DB from a previous run
    db_path = '/tmp/battlebugs_e2e.db'
    if os.path.exists(db_path):
        os.remove(db_path)
    upload_dir = '/tmp/battlebugs-e2e-uploads'
    shutil.rmtree(upload_dir, ignore_errors=True)
    os.makedirs(upload_dir, exist_ok=True)

    app = create_app(E2EConfig)
    with app.app_context():
        _db.create_all()
        _seed_db(app)

    yield app

    with app.app_context():
        _db.drop_all()


def _seed_db(app):
    """Create a few users and bugs for tests to interact with."""
    with app.app_context():
        # Create a regular user
        user = User(username='testuser', email='test@example.com', role='USER')
        user.set_password('Password1!')
        _db.session.add(user)

        # Create an admin
        admin = User(username='admin', email='admin@example.com', role='ADMIN')
        admin.set_password('Admin1!')
        _db.session.add(admin)

        _db.session.flush()

        # Create a couple of bugs
        for i, (name, tier) in enumerate([
            ('Iron Fang', 'ou'), ('Gently Used', 'zu'), ('Bone Stalker', 'uu')
        ]):
            bug = Bug(
                nickname=name,
                image_path='test.jpg',
                user_id=user.id,
                attack=30 + i * 10,
                defense=25 + i * 5,
                speed=20 + i * 8,
                tier=tier,
                stats_generated=True,
            )
            _db.session.add(bug)

        _db.session.commit()


@pytest.fixture(scope='session')
def live_server(flask_app):
    """Start Flask in a background thread; yield the base URL."""
    server_thread = threading.Thread(
        target=lambda: flask_app.run(
            host='127.0.0.1', port=E2E_PORT,
            use_reloader=False, threaded=True,
        ),
        daemon=True,
    )
    server_thread.start()
    # Wait until the port is accepting connections
    import socket
    for _ in range(30):
        try:
            with socket.create_connection(('127.0.0.1', E2E_PORT), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError(f'Flask server did not start on port {E2E_PORT}')

    yield f'http://127.0.0.1:{E2E_PORT}'


@pytest.fixture(scope='session')
def base_url(live_server):
    return live_server


# ── Helper fixtures ─────────────────────────────────────────────────────────

@pytest.fixture()
def logged_in_page(page, base_url):
    """Return a Playwright Page already logged in as testuser."""
    page.goto(f'{base_url}/login')
    page.fill('input[name="username"]', 'testuser')
    page.fill('input[name="password"]', 'Password1!')
    page.click('button[type="submit"]')
    page.wait_for_url(f'{base_url}/**')
    return page


@pytest.fixture()
def admin_page(page, base_url):
    """Return a Playwright Page already logged in as admin."""
    page.goto(f'{base_url}/login')
    page.fill('input[name="username"]', 'admin')
    page.fill('input[name="password"]', 'Admin1!')
    page.click('button[type="submit"]')
    page.wait_for_url(f'{base_url}/**')
    return page
