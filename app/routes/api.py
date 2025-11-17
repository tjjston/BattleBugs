"""
API routes for AJAX requests and external integrations
"""

from flask import Blueprint, jsonify, request
from app import db
from app.models import Species, Bug, BugAchievement
from app.services.taxonomy import TaxonomyService, StatsGenerator

bp = Blueprint('api', __name__, url_prefix='/api')

@bp.route('/species/search')
def search_species():
    """Search for species by name"""
    query = request.args.get('q', '')
    if not query:
        return jsonify({'error': 'Query parameter required'}), 400
    
    taxonomy = TaxonomyService()
    try:
        results = taxonomy.search_species(query)
        return jsonify(results), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/species/<int:species_id>')
def get_species(species_id):
    """Get detailed species information"""
    species = db.session.get(Species, species_id)
    if not species:
        return jsonify({'error': 'Species not found'}), 404
    return jsonify(species.to_dict()), 200


@bp.route('/species/<string:scientific_name>/details')
def get_species_by_name(scientific_name):
    """Get species details by scientific name"""
    taxonomy = TaxonomyService()
    
    try:
        species = taxonomy.get_species_details(scientific_name=scientific_name)
        if not species:
            return jsonify({'error': 'Species not found'}), 404
        
        return jsonify(species.to_dict()), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/bug/<int:bug_id>/regenerate-stats', methods=['POST'])
def regenerate_bug_stats(bug_id):
    """Regenerate stats for a bug based on its species"""
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return jsonify({'error': 'Bug not found'}), 404
    
    generator = StatsGenerator()
    new_stats = generator.generate_stats(bug)
    
    bug.attack = new_stats['attack']
    bug.defense = new_stats['defense']
    bug.speed = new_stats['speed']
    bug.special_ability = new_stats.get('special_ability')
    bug.stats_generated = True
    bug.stats_generation_method = 'species_based' if bug.species_info else 'random'
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'stats': new_stats,
        'bug_id': bug_id
    }), 200


@bp.route('/bug/<int:bug_id>/assign-flair', methods=['POST'])
def assign_flair(bug_id):
    """Manually assign or regenerate flair for a bug"""
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return jsonify({'error': 'Bug not found'}), 404
    
    data = request.get_json()
    custom_flair = data.get('flair') if data else None
    
    if custom_flair:
        bug.flair = custom_flair
    else:
        bug.generate_flair()
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'flair': bug.flair,
        'bug_id': bug_id
    }), 200


@bp.route('/bug/<int:bug_id>/achievements')
def get_bug_achievements(bug_id):
    """Get all achievements for a bug"""
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return jsonify({'error': 'Bug not found'}), 404
    
    achievements = [{
        'id': ach.id,
        'type': ach.achievement_type,
        'name': ach.achievement_name,
        'icon': ach.achievement_icon,
        'description': ach.description,
        'rarity': ach.rarity,
        'earned_date': ach.earned_date.strftime('%Y-%m-%d') if ach.earned_date else None
    } for ach in bug.achievements.all()]
    
    return jsonify({
        'bug_id': bug_id,
        'bug_name': bug.nickname,
        'achievements': achievements
    }), 200


@bp.route('/species/popular')
def get_popular_species():
    """Get most commonly submitted species"""
    popular = db.session.query(
        Species.scientific_name,
        Species.common_name,
        db.func.count(Bug.id).label('count')
    ).join(Bug).group_by(Species.id)\
     .order_by(db.desc('count')).limit(10).all()
    
    return jsonify([{
        'scientific_name': p[0],
        'common_name': p[1],
        'submission_count': p[2]
    } for p in popular]), 200


@bp.route('/species/stats')
def get_species_stats():
    """Get statistics about species diversity"""
    total_species = db.session.query(Species).count()
    total_bugs = db.session.query(Bug).count()
    verified_bugs = db.session.query(Bug).filter_by(is_verified=True).count()
    
    # Most common orders
    orders = db.session.query(
        Species.order,
        db.func.count(Bug.id).label('count')
    ).join(Bug).group_by(Species.order)\
     .order_by(db.desc('count')).limit(5).all()
    
    return jsonify({
        'total_species': total_species,
        'total_bugs': total_bugs,
        'verified_bugs': verified_bugs,
        'verification_rate': (verified_bugs / total_bugs * 100) if total_bugs > 0 else 0,
        'top_orders': [{'order': o[0], 'count': o[1]} for o in orders]
    }), 200