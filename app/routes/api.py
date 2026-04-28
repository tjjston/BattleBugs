"""
API routes for AJAX requests and external integrations
"""

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Species, Bug, BugAchievement
from app.services.permission_system import can_edit_bug
from app.services.economy import (
    InsufficientCurrencyError,
    STAT_REGENERATION_COST,
    should_charge_for_stat_regeneration,
    spend_currency,
)
from app.services.taxonomy import TaxonomyService, StatsGenerator

bp = Blueprint('api', __name__, url_prefix='/api')


_GLADIATOR_ADJECTIVES = [
    'Iron', 'Crimson', 'Obsidian', 'Venom', 'Shadow', 'Savage', 'Gilded',
    'Stone', 'Raging', 'Blazing', 'Frost', 'Thunder', 'Ashen', 'Scarred',
    'Dire', 'Hollow', 'Silent', 'Feral', 'Ancient', 'Grim', 'Armored',
    'Wretched', 'Cursed', 'Molten', 'Twisted', 'Phantom', 'Bone', 'War',
    'Rusted', 'Spiked', 'Noxious', 'Leaden', 'Barbed', 'Jagged', 'Blighted',
]

_GLADIATOR_NOUNS = [
    'Fang', 'Reaper', 'Wraith', 'Crusher', 'Stalker', 'Mauler', 'Titan',
    'Rend', 'Spike', 'Bane', 'Vex', 'Dagger', 'Thorn', 'Slayer', 'Hex',
    'Razor', 'Haunt', 'Ruin', 'Scourge', 'Talon', 'Grappler', 'Warden',
    'Sting', 'Drake', 'Marauder', 'Savage', 'Doom', 'Predator', 'Brute',
    'Nightmare', 'Ripper', 'Colossus', 'Ravager', 'Skewer', 'Mandible',
]


def _fallback_nicknames(context):
    import random
    common = (context.get('common_name') or '').strip()
    scientific = (context.get('scientific_name') or '').strip()
    base = (common or scientific or '').split()[0].capitalize() if (common or scientific) else None

    names = set()
    adjs = random.sample(_GLADIATOR_ADJECTIVES, min(12, len(_GLADIATOR_ADJECTIVES)))
    nouns = random.sample(_GLADIATOR_NOUNS, min(12, len(_GLADIATOR_NOUNS)))

    for adj, noun in zip(adjs, nouns):
        if base:
            names.add(f'{adj} {base}')
            names.add(f'{base} {noun}')
        names.add(f'{adj} {noun}')
        if len(names) >= 8:
            break

    result = list(names)
    random.shuffle(result)
    return result[:6]


def _fallback_lore(context):
    hint = (context.get('hint') or 'a mysterious arena challenger').strip()
    return {
        'background': f'Known in the field notes as {hint}, this warrior arrived with a reputation built in hidden places.',
        'motivation': 'Fights to earn a place among the arena legends.',
        'personality': 'Alert, stubborn, and quick to turn small openings into decisive moves.',
    }


def _fallback_species(context):
    desc = (context.get('description') or '').lower()
    if 'spider' in desc:
        return [{'common_name': 'Jumping spider', 'scientific_name': 'Salticidae specimen'}]
    if 'mantis' in desc:
        return [{'common_name': 'Mantis', 'scientific_name': 'Mantodea specimen'}]
    if 'wasp' in desc or 'bee' in desc:
        return [{'common_name': 'Wasp or bee', 'scientific_name': 'Hymenoptera specimen'}]
    if 'moth' in desc or 'butterfly' in desc:
        return [{'common_name': 'Moth or butterfly', 'scientific_name': 'Lepidoptera specimen'}]
    return [{'common_name': 'Beetle', 'scientific_name': 'Coleoptera specimen'}]


def _parse_json_list_or_lines(text):
    import json

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [line.strip('-* 0123456789.').strip() for line in text.splitlines() if line.strip()]

@bp.route('/species/search')
def search_species():
    """Search for species by name"""
    query = request.args.get('q', '')
    mode = request.args.get('mode', 'name')
    if not query:
        return jsonify({'error': 'Query parameter required'}), 400
    
    taxonomy = TaxonomyService()
    try:
        results = taxonomy.search_species(query, mode=mode)
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
@login_required
def regenerate_bug_stats(bug_id):
    """Regenerate stats for a bug based on its species"""
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return jsonify({'error': 'Bug not found'}), 404
    if not can_edit_bug(current_user, bug):
        return jsonify({'error': 'Forbidden'}), 403
    try:
        if should_charge_for_stat_regeneration(current_user, bug):
            spend_currency(
                current_user,
                STAT_REGENERATION_COST,
                'stat_regeneration',
                'bug',
                bug.id,
            )
    except InsufficientCurrencyError as exc:
        return jsonify({'error': str(exc), 'cost': STAT_REGENERATION_COST, 'balance': current_user.accolade_points or 0}), 402
    
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
@login_required
def assign_flair(bug_id):
    """Manually assign or regenerate flair for a bug"""
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return jsonify({'error': 'Bug not found'}), 404
    if not can_edit_bug(current_user, bug):
        return jsonify({'error': 'Forbidden'}), 403
    
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


@bp.route('/bug/generate', methods=['POST'])
@login_required
def generate_bug_suggestion():
    """Generate suggestions for submission fields (nickname, lore, species)

    Expects JSON: { 'field': 'nickname'|'lore'|'species', 'context': {...} }
    Returns JSON with 'suggestions' list or 'result' dict depending on field.
    """
    data = request.get_json() or {}
    field = data.get('field')
    context = data.get('context', {})

    from app.services.llm_manager import LLMService
    import json

    llm = LLMService()

    if field == 'nickname':
        common = context.get('common_name', '')
        scientific = context.get('scientific_name', '')
        prompt = (
            f"You are naming a gladiator bug for an insect battle arena. "
            f"Generate exactly 6 badass gladiator names for a {common or scientific or 'mystery bug'}. "
            f"Rules: 2-3 words max, mix of dark adjectives + creature/weapon nouns, "
            f"evoke fear or power (e.g. 'Iron Fang', 'Crimson Reaper', 'Bone Stalker', 'Venom Wraith'). "
            f"Return ONLY a JSON array of 6 name strings, nothing else."
        )
        try:
            resp = llm.generate(prompt, task='quick_tasks', max_tokens=200)
            suggestions = _parse_json_list_or_lines(resp)
            if not suggestions:
                suggestions = _fallback_nicknames(context)
            return jsonify({'field': 'nickname', 'suggestions': suggestions[:6]}), 200
        except Exception as e:
            current_app.logger.warning("Nickname generation fell back locally: %s", e)
            return jsonify({'field': 'nickname', 'suggestions': _fallback_nicknames(context), 'fallback': True}), 200

    if field == 'lore':
        hint = context.get('hint', '')
        prompt = f"""Create lore for a bug gladiator. Provide three short sections as JSON: {{"background": "...", "motivation": "...", "personality": "..."}}.\nContext hint: {hint}"""
        try:
            resp = llm.generate(prompt, task='quick_tasks', max_tokens=400)
            try:
                parsed = json.loads(resp)
            except Exception:
                parsed = {'background': resp}
            return jsonify({'field': 'lore', 'result': parsed}), 200
        except Exception as e:
            current_app.logger.warning("Lore generation fell back locally: %s", e)
            return jsonify({'field': 'lore', 'result': _fallback_lore(context), 'fallback': True}), 200

    if field == 'species':
        desc = context.get('description', '')
        prompt = f"""Given this description: {desc}\nSuggest 3 likely common names and scientific name guesses in JSON format: [{{"common_name":"", "scientific_name":""}}, ...]"""
        try:
            resp = llm.generate(prompt, task='species_identification', max_tokens=400)
            try:
                parsed = json.loads(resp)
            except Exception:
                parsed = _fallback_species(context)
            return jsonify({'field': 'species', 'suggestions': parsed}), 200
        except Exception as e:
            current_app.logger.warning("Species generation fell back locally: %s", e)
            return jsonify({'field': 'species', 'suggestions': _fallback_species(context), 'fallback': True}), 200

    return jsonify({'error': 'Unknown field'}), 400
