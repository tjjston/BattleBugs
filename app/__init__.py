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


