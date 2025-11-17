"""
Routes package initialization.
Import blueprints here to make them available.
"""
from app.routes import main, auth, bugs, battles, tournaments, admin, api

__all__ = ['main', 'auth', 'bugs', 'battles', 'tournaments', 'admin', 'api']