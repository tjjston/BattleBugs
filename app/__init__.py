from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate = Migrate(app, db)

    # Enable WAL mode + busy timeout on SQLite so web requests aren't blocked
    # when the job-queue thread holds a write lock during long LLM calls.
    from sqlalchemy import event, text as _sa_text
    from sqlalchemy.engine import Engine as _Engine
    import sqlite3 as _sqlite3

    @event.listens_for(_Engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _conn_record):
        if isinstance(dbapi_conn, _sqlite3.Connection):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=10000")   # 10 s — fail fast, not hang
            cur.close()

    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Compatibility shim: some Flask/Werkzeug combinations pass a 'partitioned' kw
    # to Response.set_cookie which older Werkzeug versions don't accept. Wrap
    # the method to silently ignore 'partitioned' so sessions save without error.
    try:
        from flask.wrappers import Response as _FlaskResponse
        _orig_set_cookie = _FlaskResponse.set_cookie

        def _set_cookie_compat(self, *args, **kwargs):
            if 'partitioned' in kwargs:
                kwargs.pop('partitioned', None)
            return _orig_set_cookie(self, *args, **kwargs)

        _FlaskResponse.set_cookie = _set_cookie_compat
    except Exception:
        # If anything goes wrong here, fail silently — it only affects cookie
        # argument compatibility for older Werkzeug versions.
        pass

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('database', exist_ok=True)
    
    with app.app_context():
        from app import models
    
    # Register blueprints
    from app.routes import main, auth, bugs, battles, tournaments, api, admin, championship
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(bugs.bp)
    app.register_blueprint(battles.bp)
    app.register_blueprint(tournaments.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(championship.bp)

    # Custom Jinja2 filters
    import json as _json
    @app.template_filter('fromjson')
    def _fromjson(value):
        try:
            return _json.loads(value) if isinstance(value, str) else value
        except Exception:
            return []

    # Inject permission helpers globally so templates can call is_admin/is_owner
    from app.services.permission_system import can_view_secrets, is_admin, is_moderator, is_owner
    @app.context_processor
    def inject_permission_helpers():
        return {
            'can_view_secrets': lambda: can_view_secrets(current_user),
            'is_admin': lambda: is_admin(current_user),
            'is_moderator': lambda: is_moderator(current_user),
            'is_owner': lambda: is_owner(current_user)
        }

    if not app.config.get('TESTING'):
        from app.services.job_queue import start_scheduler
        start_scheduler(app)

        # Warm the quick-task model so the first user request doesn't pay
        # Ollama's cold-load (often 15-30 s, which manifests as an empty
        # response). One small ping is enough — Ollama then keeps the model
        # resident for its idle timeout.
        import threading as _threading
        def _warmup_quick_tasks(flask_app):
            try:
                with flask_app.app_context():
                    from app.services.llm_manager import LLMService
                    LLMService().generate('hi', task='quick_tasks', max_tokens=5)
            except Exception:
                pass
        _threading.Thread(target=_warmup_quick_tasks, args=(app,), daemon=True).start()

    return app
