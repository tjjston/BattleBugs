from flask import Blueprint, render_template
from app import db
from app.models import Bug, Battle, Tournament
from sqlalchemy import desc, func

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """Homepage showing recent activity"""
    # Get latest battles
    latest_battles = db.session.query(Battle).order_by(
        desc(Battle.battle_date)
    ).limit(5).all()
    
    # Get upcoming tournaments
    upcoming_tournaments = db.session.query(Tournament).filter(
        Tournament.start_date >= func.current_date()
    ).order_by(Tournament.start_date).limit(5).all()
    
    # Get top bugs by wins
    top_bugs = db.session.query(Bug).order_by(
        desc(Bug.wins)
    ).limit(10).all()  # Get 10 so template can show top 5
    
    # Get recent battles for display
    recent_battles = latest_battles  # Alias for clarity in template
    
    return render_template('index.html', 
                         battles=recent_battles,
                         recent_battles=recent_battles,  # For backwards compatibility
                         tournaments=upcoming_tournaments,
                         bugs=top_bugs,  # Some templates use 'bugs'
                         top_bugs=top_bugs)  # Some templates use 'top_bugs'

@bp.route('/hall-of-fame')
def hall_of_fame():
    """Hall of Fame page showing top bugs and tournament champions"""
    # Get top bugs by win rate (minimum 5 battles)
    top_bugs = db.session.query(Bug).filter(
        (Bug.wins + Bug.losses) >= 5
    ).order_by(desc(Bug.wins)).limit(20).all()
    
    # Get completed tournaments
    tournaments = db.session.query(Tournament).filter_by(
        status='completed'
    ).order_by(desc(Tournament.end_date)).limit(10).all()
    
    return render_template('hall_of_fame.html', 
                         top_bugs=top_bugs, 
                         tournaments=tournaments)