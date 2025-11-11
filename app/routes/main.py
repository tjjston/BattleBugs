from flask import Blueprint, render_template
from app.models import Bug, Battle, Tourmanent
from sqlalchemy import desc

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    latest_battles = Battle.query.order_by(desc(Battle.timestamp)).limit(5).all()
    upcoming_tournaments = Tourmanent.query.filter(Tourmanent.date >= func.current_date()).order_by(Tourmanent.date).limit(5).all()
    popular_bugs = Bug.query.order_by(desc(Bug.popularity)).limit(5).all()
    return render_template('index.html', battles=latest_battles, tournaments=upcoming_tournaments, bugs=popular_bugs)