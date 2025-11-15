from flask import Flask
from config import Config
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bootstrap import Bootstrap
from flask_login import LoginManager
import os

db = SQLAlchemy()
loginManager = LoginManager()
login_manager.login_view = 'auth.login'
bootstrap = Bootstrap()
login_manager.login_message = 'Please log in to access this page.'

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate = Migrate(app, db)
    loginManager.init_app(app)
    bootstrap.init_app(app)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('database', exist_ok=True)
    
    from app.routes import main, auth, bugs, battles, tournaments
    app.register_blueprint(main.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(bugs.bp)
    app.register_blueprint(battles.bp)
    app.register_blueprint(tournaments.bp)

    return app
from app import models