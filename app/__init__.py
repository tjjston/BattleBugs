from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bootstrap import Bootstrap
from flask_login import LoginManager, current_user
import os

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
bootstrap = Bootstrap()
login_manager.login_message = 'Please log in to access this page.'

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate = Migrate(app, db)
    login_manager.init_app(app)
    bootstrap.init_app(app)

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
    from app.routes import main, auth, bugs, battles, tournaments, api, admin
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(bugs.bp)
    app.register_blueprint(battles.bp)
    app.register_blueprint(tournaments.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(admin.bp)

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

    return app


