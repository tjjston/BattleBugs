"""
API routes for AJAX requests and external integrations
"""

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from app import db, csrf
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
csrf.exempt(bp)  # JSON API — CSRF is enforced via same-origin + login_required


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


@bp.route('/bug/<int:bug_id>/facts/sample')
def get_bug_random_facts(bug_id):
    """Return a random sample of N species facts for shuffle refresh.

    Query params: ?count=3 (default 3, capped at 10).
    """
    import json as _json
    import random as _r

    bug = db.session.get(Bug, bug_id)
    if not bug:
        return jsonify({'error': 'Bug not found'}), 404

    try:
        count = max(1, min(10, int(request.args.get('count', 3))))
    except (TypeError, ValueError):
        count = 3

    pool = []
    if bug.species_info and bug.species_info.interesting_facts:
        try:
            raw = _json.loads(bug.species_info.interesting_facts) or []
            pool = [f for f in raw if isinstance(f, str) and f.strip()]
        except Exception:
            pool = []

    if not pool:
        return jsonify({'bug_id': bug_id, 'facts': [], 'pool_size': 0}), 200

    _r.shuffle(pool)
    return jsonify({
        'bug_id': bug_id,
        'facts': pool[:count],
        'pool_size': len(pool),
    }), 200


@bp.route('/bug/<int:bug_id>/stats-reasoning')
def get_bug_stats_reasoning(bug_id):
    """Return the LLM's per-stat explanation for a bug, if available."""
    import json as _json
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return jsonify({'error': 'Bug not found'}), 404

    raw = bug.stats_reasoning
    if not raw:
        return jsonify({
            'bug_id': bug_id,
            'has_reasoning': False,
            'reasoning': None,
        }), 200

    try:
        parsed = _json.loads(raw)
    except (TypeError, ValueError):
        parsed = {'summary': raw}

    ability_info = None
    if bug.ability_slug:
        from app.services import ability_catalog as _ac
        a = _ac.get(bug.ability_slug)
        if a:
            ability_info = {
                'slug': a.slug,
                'name': a.name,
                'description': a.description,
                'effect': _ac.describe_effect(a),
            }

    return jsonify({
        'bug_id': bug_id,
        'bug_name': bug.nickname,
        'has_reasoning': True,
        'method': bug.stats_generation_method,
        'special_ability': bug.special_ability,
        'ability': ability_info,
        'tier': bug.tier,
        'stats': {
            'attack': bug.attack,
            'defense': bug.defense,
            'speed': bug.speed,
            'lethality': bug.lethality,
            'grip': bug.grip,
            'cunning': bug.cunning,
        },
        'reasoning': parsed,
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
        return jsonify({'field': 'nickname', 'suggestions': _fallback_nicknames(context), 'fallback': True}), 200

    if field == 'lore':
        hint = context.get('hint', '')
        prompt = (
            "Write punchy gladiator lore for a single bug.\n"
            f"Context hint: {hint or '(none)'}\n\n"
            "Return ONLY this JSON (no prose, no markdown fences):\n"
            '{"background": "<one sentence, max 30 words>",'
            ' "motivation": "<one sentence, max 25 words>",'
            ' "personality": "<one sentence, max 20 words>"}'
        )
        def _try_parse(text):
            if not text:
                return None
            import re as _re
            try:
                return json.loads(text)
            except Exception:
                m = _re.search(r'\{[^{}]*\}', text, _re.DOTALL)
                if m:
                    try:
                        return json.loads(m.group())
                    except Exception:
                        return None
            return None

        parsed = None
        last_error = None
        for _attempt in range(2):
            try:
                resp = llm.generate(prompt, task='quick_tasks', max_tokens=600, json_mode=True)
            except Exception as exc:
                last_error = str(exc)
                current_app.logger.warning("Lore generation attempt %d failed: %s", _attempt + 1, exc)
                continue
            parsed = _try_parse(resp)
            if parsed:
                break

        if parsed:
            return jsonify({'field': 'lore', 'result': parsed}), 200

        current_app.logger.warning("Lore generation falling back — last_error=%s", last_error)
        return jsonify({
            'field': 'lore',
            'result': _fallback_lore(context),
            'fallback': True,
            'message': 'The local LLM did not respond — placeholder lore was filled in. Edit it manually or try again in a moment.',
        }), 200

    if field == 'species':
        desc = context.get('description', '')
        prompt = f"""Given this description: {desc}\nSuggest 3 likely common names and scientific name guesses in JSON format: [{{"common_name":"", "scientific_name":""}}, ...]\nRespond with a valid JSON array only."""
        try:
            resp = llm.generate(prompt, task='species_identification', max_tokens=400, json_mode=True)
            try:
                parsed = json.loads(resp)
            except Exception:
                parsed = _fallback_species(context)
            return jsonify({'field': 'species', 'suggestions': parsed}), 200
        except Exception as e:
            current_app.logger.warning("Species generation fell back locally: %s", e)
            return jsonify({'field': 'species', 'suggestions': _fallback_species(context), 'fallback': True}), 200

    return jsonify({'error': 'Unknown field'}), 400


@bp.route('/validate-photo', methods=['POST'])
@login_required
def validate_photo():
    """Pre-validate a bug photo before full submission.

    Checks file size, image dimensions, duplicate hash, and (if enabled)
    the HuggingFace classifier.  Returns a JSON payload the front-end uses
    to show immediate feedback without waiting for the full submission pipeline.
    """
    import io
    from PIL import Image
    import imagehash
    from app.models import BlockedImageHash

    file = request.files.get('photo')
    if not file or not file.filename:
        return jsonify({'valid': False, 'errors': ['No file provided.']}), 400

    errors = []
    warnings = []
    info = {}

    raw = file.read()
    size_kb = len(raw) / 1024
    info['size_kb'] = round(size_kb, 1)

    if size_kb < 2:
        errors.append('Image is too small (under 2 KB). Please upload a real photo.')

    max_mb = current_app.config.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024) / (1024 * 1024)
    if size_kb > max_mb * 1024:
        errors.append(f'File exceeds the {max_mb:.0f} MB size limit.')

    try:
        filename_lower = (file.filename or '').lower()
        if filename_lower.endswith(('.heic', '.heif')):
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass
        img = Image.open(io.BytesIO(raw))
        img.verify()
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        info['dimensions'] = f'{w}x{h}'
        info['format'] = img.format or 'unknown'

        if w < 100 or h < 100:
            errors.append(f'Image is too small ({w}x{h} px). Minimum 100×100 px required.')
        elif w < 300 or h < 300:
            warnings.append(f'Image is quite small ({w}x{h} px). A larger photo will give the AI more detail.')

        if w > 6000 or h > 6000:
            warnings.append(f'Very large image ({w}x{h} px) — it will be resized during processing.')

    except Exception:
        errors.append('Could not read the file as an image. Please upload a valid photo (JPEG, PNG, WebP, etc.).')
        return jsonify({'valid': False, 'errors': errors, 'warnings': warnings, 'info': info})

    # Duplicate / blocked hash check
    try:
        phash = str(imagehash.phash(img))
        info['phash'] = phash

        if BlockedImageHash.query.filter_by(image_hash=phash).first():
            errors.append('This photo has been permanently blocked from submission.')
        elif Bug.query.filter_by(image_hash=phash).first():
            warnings.append('A bug with this photo already exists in the arena. Duplicate submissions are rejected.')
    except Exception:
        pass

    # Optional: lightweight Poseidon classifier pre-check.
    # Save the bytes to a temp file because PoseidonPipeline.classify() takes a path.
    try:
        classifier_enabled = current_app.config.get('HF_BUG_CLASSIFIER_ENABLED', True)
        classifier_required = current_app.config.get('HF_BUG_CLASSIFIER_REQUIRED', False)
        if classifier_enabled and current_app.config.get('BUG_CLASSIFIER_URL'):
            import tempfile, os as _os
            from app.services.poseidon_pipeline import PoseidonPipeline
            suffix = '.' + (file.filename.rsplit('.', 1)[-1] if file.filename and '.' in file.filename else 'jpg')
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            try:
                pipeline = PoseidonPipeline()
                predictions, source = pipeline.classify(tmp_path)
                if predictions:
                    prediction = predictions[0]
                    min_conf = current_app.config.get('HF_BUG_CLASSIFIER_MIN_CONFIDENCE', 0.80)
                    info['classifier_label'] = prediction.scientific_name or ''
                    info['classifier_confidence'] = round(prediction.confidence, 3)
                    info['classifier_source'] = source

                    if prediction.rank == 'non_arthropod':
                        msg = f'The classifier thinks this may not be an arthropod ({prediction.scientific_name}, {prediction.confidence:.0%}).'
                        if classifier_required:
                            errors.append(msg)
                        else:
                            warnings.append(msg)
                    elif prediction.confidence < min_conf:
                        msg = (f'The classifier is not confident about this image '
                               f'({prediction.scientific_name}, {prediction.confidence:.0%}). '
                               f'Submissions below {min_conf:.0%} confidence may need review.')
                        if classifier_required:
                            errors.append(msg)
                        else:
                            warnings.append(msg)
            finally:
                _os.unlink(tmp_path)
    except Exception as exc:
        current_app.logger.debug('Classifier pre-check skipped: %s', exc)

    valid = len(errors) == 0
    return jsonify({'valid': valid, 'errors': errors, 'warnings': warnings, 'info': info})
