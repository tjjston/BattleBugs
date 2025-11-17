from flask import Blueprint, render_template
from app.models import Bug, Battle, Tournament
from sqlalchemy import desc

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    latest_battles = Battle.query.order_by(desc(Battle.battle_date)).limit(5).all()
    
    upcoming_tournaments = Tournament.query.filter(
        Tournament.start_date >= func.current_date()
    ).order_by(Tournament.start_date).limit(5).all()
    
    popular_bugs = Bug.query.order_by(desc(Bug.wins)).limit(5).all()
    
    return render_template('index.html', 
                         battles=latest_battles, 
                         tournaments=upcoming_tournaments, 
                         bugs=popular_bugs)

@bp.route('/hall-of-fame')
def hall_of_fame():
    """Hall of Fame page showing top bugs and tournament champions"""
    top_bugs = Bug.query.filter(
        (Bug.wins + Bug.losses) >= 5
    ).order_by(desc(Bug.wins)).limit(20).all()
    
    tournaments = Tournament.query.filter_by(
        status='completed'
    ).order_by(desc(Tournament.end_date)).limit(10).all()
    
    return render_template('hall_of_fame.html', 
                         top_bugs=top_bugs, 
                         tournaments=tournaments)