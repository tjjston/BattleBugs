"""
Complete Enhanced Bug Submission Route
Integrates: Vision verification, duplicate detection, LLM stats, tier assignment
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Bug, Species, Comment, BugLore, CommentVote, BugLoreVote, Job, BugRival, ClassificationFlag, BlockedImageHash, RejectedSubmission
from sqlalchemy import func
from app.services.vision_service import comprehensive_bug_verification
from app.services.tier_system import LLMStatGenerator, TierSystem, assign_tier_and_generate_stats
from app.services.taxonomy import TaxonomyService
from app.services.permission_system import require_role, UserRole
from app.services.economy import (
    InsufficientCurrencyError,
    STAT_REGENERATION_COST,
    should_charge_for_stat_regeneration,
    spend_currency,
)
import json
import os
from datetime import datetime
import imagehash
from PIL import Image


bp = Blueprint('bugs', __name__)


def _save_rejected_for_review(temp_path, user_id, nickname, description,
                               location_found, user_species_guess, rejection_reasons):
    """Move the rejected image to the review folder and persist a RejectedSubmission record."""
    try:
        review_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], 'review')
        os.makedirs(review_dir, exist_ok=True)
        review_filename = f"review_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.path.basename(temp_path)}"
        review_path = os.path.join(review_dir, review_filename)
        os.rename(temp_path, review_path)
        record = RejectedSubmission(
            user_id=user_id,
            image_path=f'review/{review_filename}',
            nickname=nickname,
            description=description,
            location_found=location_found,
            user_species_guess=user_species_guess,
            rejection_reasons=json.dumps(rejection_reasons or []),
        )
        db.session.add(record)
        db.session.commit()
    except Exception as e:
        current_app.logger.warning("Could not save rejected submission for review: %s", e)
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

@bp.route('/bugs')
def list_bugs():
    """List all bugs with pagination"""
    page = request.args.get('page', 1, type=int)

    # Filters: search (name/species), tier, mine (show only current user's bugs)
    search = request.args.get('search', type=str)
    tier = request.args.get('tier', type=str)
    mine = request.args.get('mine', default=0, type=int)
    species_id = request.args.get('species_id', type=int)

    query = Bug.query

    if mine and current_user.is_authenticated:
        query = query.filter(Bug.user_id == current_user.id)

    if tier:
        query = query.filter(Bug.tier == tier)

    if species_id:
        query = query.filter(Bug.species_id == species_id)

    if search:
        likeq = f"%{search}%"
        query = query.filter(
            (Bug.nickname.ilike(likeq)) |
            (Bug.common_name.ilike(likeq)) |
            (Bug.scientific_name.ilike(likeq))
        )

    bugs = query.order_by(Bug.submission_date.desc())\
        .paginate(page=page, per_page=current_app.config.get('BUGS_PER_PAGE', 20), error_out=False)

    # Provide available tiers for the filter dropdown
    tiers = db.session.query(Bug.tier).distinct().all()
    tiers = [t[0] for t in tiers if t[0]]

    return render_template('bug_list.html', bugs=bugs, tiers=tiers, active_filters={'search': search, 'tier': tier, 'mine': mine, 'species_id': species_id})

@bp.route('/bug/<int:bug_id>')
def view_bug(bug_id):
    """View individual bug profile"""
    bug = db.get_or_404(Bug, bug_id)
    comments = Comment.query.filter_by(bug_id=bug_id)\
        .order_by(Comment.created_at.desc()).all()
    lore = BugLore.query.filter_by(bug_id=bug_id)\
        .order_by(BugLore.upvotes.desc()).all()
    jobs = Job.query.filter(Job.payload_json.contains(f'"bug_id": {bug.id}'))\
        .order_by(Job.created_at.desc()).all()
    rivals = BugRival.query.filter(
        ((BugRival.bug1_id == bug.id) | (BugRival.bug2_id == bug.id)) &
        (BugRival.encounter_count >= 2)
    ).order_by(BugRival.encounter_count.desc()).limit(5).all()

    show_exact_stats = (
        current_user.is_authenticated and
        (current_user.id == bug.user_id or
         current_user.role in ('MODERATOR', 'ADMIN', 'OWNER'))
    )
    return render_template('bug_profile.html',
                         bug=bug,
                         comments=comments,
                         lore=lore,
                         jobs=jobs,
                         rivals=rivals,
                         show_exact_stats=show_exact_stats)

def handle_submission():
    """Process bug submission with LLM-controlled classification"""
    
    # Get form data
    nickname = request.form.get('nickname')
    description = request.form.get('description')
    location_found = request.form.get('location_found')
    user_species_guess = request.form.get('user_species_guess')
    send_to_admin_review = bool(request.form.get('send_to_admin_review'))

    # Get user lore fields
    lore_data = {
        'background': request.form.get('lore_background'),
        'motivation': request.form.get('lore_motivation'),
        'personality': request.form.get('lore_personality'),
        'interests': request.form.get('lore_interests'),
        'religion': request.form.get('lore_religion'),
        'fears': request.form.get('lore_fears'),
        'allies': request.form.get('lore_allies'),
        'rivals': request.form.get('lore_rivals')
    }
    
    # Handle image upload
    if 'image' not in request.files:
        flash('No image provided', 'danger')
        return redirect(url_for('bugs.submit_bug'))
    
    file = request.files['image']
    
    if file.filename == '':
        flash('No image selected', 'danger')
        return redirect(url_for('bugs.submit_bug'))
    
    if not allowed_file(file.filename):
        flash('Invalid file type', 'danger')
        return redirect(url_for('bugs.submit_bug'))
    
    # Save temporary file
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_filename = f"temp_{current_user.id}_{timestamp}_{filename}"
    temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], temp_filename)
    try:
        os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
        file.save(temp_path)
    except OSError as e:
        current_app.logger.exception("Could not save uploaded bug image")
        flash(f'Could not save upload. Check UPLOAD_FOLDER permissions: {e}', 'danger')
        return redirect(url_for('bugs.submit_bug'))

    # Convert HEIC/HEIF/TIFF/BMP → JPEG so downstream tools (imagehash, LLM) work
    ext_raw = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext_raw in ('heic', 'heif', 'tiff', 'tif', 'bmp'):
        try:
            if ext_raw in ('heic', 'heif'):
                try:
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                except ImportError:
                    pass  # try Pillow directly; may work on some builds
            converted_path = temp_path.rsplit('.', 1)[0] + '.jpg'
            img_conv = Image.open(temp_path).convert('RGB')
            img_conv.save(converted_path, 'JPEG', quality=92)
            os.remove(temp_path)
            temp_path = converted_path
            temp_filename = os.path.basename(converted_path)
        except Exception as conv_err:
            current_app.logger.warning("Could not convert %s to JPEG: %s", ext_raw, conv_err)
            flash(f'Could not process {ext_raw.upper()} file. Try converting to JPEG first.', 'danger')
            os.remove(temp_path)
            return redirect(url_for('bugs.submit_bug'))

    try:
        # --- Duplicate / blocked image hash check (before LLM call to save quota) ---
        candidate_hash = imagehash.average_hash(Image.open(temp_path))
        h_str = str(candidate_hash)

        # Permanently blocked hashes (e.g. failed zombug conversions)
        if BlockedImageHash.query.filter_by(image_hash=h_str).first():
            os.remove(temp_path)
            flash('This image was previously rejected during Zombugification and cannot be resubmitted.', 'danger')
            return redirect(url_for('bugs.submit_bug'))

        # Near-duplicate of existing approved bug
        for (existing_h,) in db.session.query(Bug.image_hash).filter(Bug.image_hash.isnot(None)).all():
            try:
                if imagehash.hex_to_hash(existing_h) - candidate_hash <= 8:
                    os.remove(temp_path)
                    flash('This bug image has already been submitted.', 'danger')
                    return redirect(url_for('bugs.submit_bug'))
            except Exception:
                continue

        # LLM Classification
        from app.services.bug_classifier import classify_bug_submission
        
        classification = classify_bug_submission(
            image_path=temp_path,
            user_id=current_user.id,
            nickname=nickname,
            description=description,
            user_species_guess=user_species_guess
        )
        
        # Track species-guess accuracy (cosmetic badge; counted on every attempt)
        if user_species_guess:
            current_user.total_guesses = (current_user.total_guesses or 0) + 1
            if classification.user_guess_matches:
                current_user.correct_guesses = (current_user.correct_guesses or 0) + 1
        else:
            current_user.skipped_guesses = (current_user.skipped_guesses or 0) + 1
        db.session.flush()  # persist counters; rolled back with session on hard failure

        # Check if LLM approved
        if not classification.approved:
            flash('❌ Submission Rejected', 'danger')
            for reason in classification.rejection_reasons:
                flash(f'• {reason}', 'warning')

            if classification.user_guess_feedback:
                flash(f'About your identification: {classification.user_guess_feedback}', 'info')

            if send_to_admin_review:
                _save_rejected_for_review(
                    temp_path=temp_path,
                    user_id=current_user.id,
                    nickname=nickname,
                    description=description,
                    location_found=location_found,
                    user_species_guess=user_species_guess,
                    rejection_reasons=classification.rejection_reasons,
                )
                flash('Your submission has been sent to the admins for manual review.', 'info')
            else:
                os.remove(temp_path)

            return redirect(url_for('bugs.submit_bug'))
        
        # LLM APPROVED - check condition before committing
        condition = getattr(classification, 'condition', 'alive') or 'alive'
        condition_notes = getattr(classification, 'condition_notes', None) or None

        if condition == 'dead':
            from app.services.condition_system import roll_zombug_success
            if not roll_zombug_success():
                os.remove(temp_path)
                # Permanently block this hash so the image can't be resubmitted
                try:
                    blocked = BlockedImageHash(image_hash=str(candidate_hash), reason='zombug_failed')
                    db.session.add(blocked)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                flash(
                    '🧟 Zombugification failed! The reanimation ritual was unsuccessful — '
                    'this specimen did not survive the process. The image has been permanently blocked.',
                    'danger',
                )
                return redirect(url_for('bugs.submit_bug'))

        final_filename = f"{current_user.id}_{timestamp}_{filename}"
        final_path = os.path.join(current_app.config['UPLOAD_FOLDER'], final_filename)
        os.rename(temp_path, final_path)
        
        # Get/create species
        species_info = None
        if classification.scientific_name:
            from app.services.taxonomy import TaxonomyService
            taxonomy = TaxonomyService()
            
            species_info = taxonomy.get_species_details(
                scientific_name=classification.scientific_name
            )
            
            if not species_info and classification.order:
                species_info = Species(
                    scientific_name=classification.scientific_name,
                    common_name=classification.common_name,
                    order=classification.order,
                    family=classification.family,
                    data_source='llm_vision'
                )
                db.session.add(species_info)
                db.session.flush()

        # --- Season/species uniqueness check ---
        if species_info and getattr(species_info, 'id', None):
            from app.services.seasonal_tournament import get_season_for_date, get_season_date_range
            _sn, _sy = get_season_for_date()
            _ss, _se = get_season_date_range(_sn, _sy)
            existing_this_season = Bug.query.filter(
                Bug.user_id == current_user.id,
                Bug.species_id == species_info.id,
                Bug.is_retired.isnot(True),
                Bug.submission_date.between(_ss, _se),
            ).first()
            if existing_this_season:
                os.remove(final_path)
                db.session.rollback()
                species_label = classification.common_name or species_info.common_name or 'this species'
                flash(
                    f'You already have an active {species_label} this season. '
                    'Each user can only enter one bug per species per season.',
                    'danger',
                )
                return redirect(url_for('bugs.submit_bug'))

        # Create Bug entry
        bug = Bug(
            nickname=nickname,
            description=description,
            location_found=location_found,
            image_path=final_filename,
            user_id=current_user.id,
            
            # LLM classification data
            vision_verified=True,
            vision_confidence=classification.confidence,
            vision_identified_species=classification.identified_species,
            
            # Species linkage
            species_id=species_info.id if species_info else None,
            common_name=classification.common_name,
            scientific_name=classification.scientific_name,
            
            # User lore
            lore_background=lore_data.get('background'),
            lore_motivation=lore_data.get('motivation'),
            lore_personality=lore_data.get('personality'),
            lore_interests=lore_data.get('interests'),
            lore_religion=lore_data.get('religion'),
            lore_fears=lore_data.get('fears'),
            lore_allies=lore_data.get('allies'),
            lore_rivals=lore_data.get('rivals'),
            
            image_hash=str(candidate_hash),
            requires_manual_review=(classification.confidence < 0.90)
        )
        
        db.session.add(bug)
        db.session.flush()  # Get bug.id before proceeding
        
        # Generate stats using LLM
        from app.services.tier_system import LLMStatGenerator, TierSystem, TIER_DEFINITIONS
        
        stat_generator = LLMStatGenerator()
        bug_info = {
            'scientific_name': bug.scientific_name,
            'common_name': bug.common_name,
            'size_mm': bug.species_info.average_size_mm if bug.species_info else None,
            'traits': _extract_traits_from_bug(bug),
            'species_info': bug.species_info.to_dict() if bug.species_info else None
        }
        
        stats = stat_generator.generate_stats_with_llm(bug_info)
        bug.attack = stats['attack']
        bug.defense = stats['defense']
        bug.speed = stats['speed']
        bug.lethality = stats.get('lethality', 50)
        bug.grip = stats.get('grip', 50)
        bug.cunning = stats.get('cunning', 50)
        bug.special_ability = stats.get('special_ability')
        bug.stats_generation_method = 'llm_contextual'
        bug.stats_generated = True

        # Apply condition modifiers (dead, squashed, damaged, etc.)
        if condition and condition != 'alive':
            from app.services.condition_system import apply_condition_modifiers
            lore_entry = apply_condition_modifiers(bug, condition, llm_notes=condition_notes)
            bug.condition_notes = lore_entry
            if condition == 'dead':
                bug.is_zombug = True
        else:
            bug.condition = 'alive'

        # Assign tier
        bug.tier = TierSystem.assign_tier(bug)
        tier_info = TIER_DEFINITIONS.get(bug.tier, {})
        
        # Queue slower enrichment work so submission stays responsive.
        from app.services.achievements import award_submission_achievements
        from app.services.job_queue import enqueue_bug_enrichment

        award_submission_achievements(bug)
        bug.generate_flair()
        enqueue_bug_enrichment(bug, final_path)
        
        # Success messages
        if user_species_guess:
            if classification.user_guess_matches:
                flash(f'✅ Excellent identification! {classification.user_guess_feedback}', 'success')
            elif classification.user_guess_matches is False:
                flash(f'ℹ️ {classification.user_guess_feedback}', 'info')
        
        flash(f'✅ {nickname} approved and entered the arena!', 'success')
        flash(f'{tier_info.get("icon", "")} {tier_info.get("name", bug.tier)}', 'info')

        if bug.is_zombug:
            flash('🧟 Zombugification successful! This bug has been reanimated with modified combat stats.', 'warning')
        elif condition and condition != 'alive':
            from app.services.condition_system import condition_display
            disp = condition_display(condition)
            flash(f'{disp["label"]} — condition detected and stat modifiers applied.', 'warning')
        
        for warning in classification.warnings:
            flash(f'⚠️ {warning}', 'warning')
        
        flash(f'Classified by: {classification.llm_provider}', 'info')
        
        # NOW redirect (bug.id exists!)
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
        current_app.logger.error(f"Bug submission error: {e}", exc_info=True)
        return redirect(url_for('bugs.submit_bug'))

@bp.route('/bug/submit', methods=['GET', 'POST'])
@login_required
def submit_bug():
    """
    Bug submission with full verification pipeline
    """
    if request.method == 'POST':
        return handle_submission()
    
    return render_template('submit_bug.html')


def _can_edit_bug(bug):
    if not current_user.is_authenticated:
        return False
    if current_user.id == bug.user_id:
        return True
    return getattr(current_user, 'role', 'USER') in ['MODERATOR', 'ADMIN', 'OWNER']


@bp.route('/bug/<int:bug_id>/recalc', methods=['GET'])
@login_required
def recalc_bug_stats(bug_id):
    """Preview LLM-recalculated stats with option to adjust before applying."""
    bug = db.get_or_404(Bug, bug_id)
    if not _can_edit_bug(bug):
        flash('You do not have permission to recalculate this bug\'s stats.', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))
    costs_points = should_charge_for_stat_regeneration(current_user, bug)
    if costs_points and (current_user.accolade_points or 0) < STAT_REGENERATION_COST:
        flash(f'Stat regeneration costs {STAT_REGENERATION_COST} Accolade Points. You have {current_user.accolade_points or 0}.', 'warning')
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))

    stat_generator = LLMStatGenerator()
    bug_info = {
        'scientific_name': bug.scientific_name,
        'common_name': bug.common_name,
        'size_mm': bug.species_info.average_size_mm if bug.species_info else None,
        'traits': _extract_traits_from_bug(bug),
        'species_info': bug.species_info.to_dict() if bug.species_info else None
    }
    stats = stat_generator.generate_stats_with_llm(bug_info)

    proposed = {
        'attack': max(0, min(100, int(stats['attack'] ))),
        'defense': max(0, min(100, int(stats['defense'] ))),
        'speed': max(0, min(100, int(stats['speed'] ))),
        'special_ability': stats.get('special_ability') or bug.special_ability,
        'reasoning': stats.get('reasoning') or ''
    }

    class _Tmp:  # minimal object for tier calc
        pass
    tmp = _Tmp()
    tmp.attack, tmp.defense, tmp.speed = proposed['attack'], proposed['defense'], proposed['speed']
    proposed_tier = TierSystem.assign_tier(tmp)

    return render_template(
        'recalc_stats.html',
        bug=bug,
        current={'attack': bug.attack, 'defense': bug.defense, 'speed': bug.speed, 'special_ability': bug.special_ability, 'tier': bug.tier},
        proposed={**proposed, 'tier': proposed_tier},
        stat_regeneration_cost=STAT_REGENERATION_COST,
        costs_points=costs_points,
        accolade_balance=current_user.accolade_points or 0
    )


@bp.route('/bug/<int:bug_id>/recalc/confirm', methods=['POST'])
@login_required
def confirm_recalc_bug_stats(bug_id):
    bug = db.get_or_404(Bug, bug_id)
    if not _can_edit_bug(bug):
        flash('You do not have permission to update this bug\'s stats.', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))

    try:
        attack = int(request.form.get('attack'))
        defense = int(request.form.get('defense'))
        speed = int(request.form.get('speed'))
        special_ability = request.form.get('special_ability')
        reasoning = request.form.get('reasoning')
        override_tier = request.form.get('override_tier') == '1'
        selected_tier = request.form.get('tier')

        for v in (attack, defense, speed):
            if v < 0 or v > 100:
                raise ValueError('Stats must be between 0 and 100')

        if should_charge_for_stat_regeneration(current_user, bug):
            spend_currency(
                current_user,
                STAT_REGENERATION_COST,
                'stat_regeneration',
                'bug',
                bug.id,
            )

        bug.attack = attack
        bug.defense = defense
        bug.speed = speed
        bug.special_ability = special_ability
        bug.stats_generation_method = 'llm_recalc_reviewed'
        bug.stats_generated = True

        if override_tier and selected_tier:
            bug.tier = selected_tier
        else:
            bug.tier = TierSystem.assign_tier(bug)

        db.session.commit()
        flash('Stats updated successfully.', 'success')
    except InsufficientCurrencyError as e:
        db.session.rollback()
        flash(str(e), 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to update stats: {e}', 'danger')

    return redirect(url_for('bugs.view_bug', bug_id=bug.id))


@bp.route('/bug/<int:bug_id>/recalc/deny', methods=['POST'])
@login_required
def deny_recalc_bug_stats(bug_id):
    bug = db.get_or_404(Bug, bug_id)
    if not _can_edit_bug(bug):
        flash('You do not have permission to modify this bug.', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))
    flash('Recalculated stats discarded. No changes applied.', 'info')
    return redirect(url_for('bugs.view_bug', bug_id=bug.id))


@bp.route('/insectidex')
@bp.route('/pokedex')
def insectidex():
    """Species index with pioneer discovery data."""
    from app.models import BugAchievement, User as _User
    search = request.args.get('search', type=str)

    species_query = db.session.query(
        Species.id,
        Species.common_name,
        Species.scientific_name,
        Species.order,
        Species.family,
        func.count(Bug.id).label('count'),
        func.max(Bug.submission_date).label('last_seen'),
        func.min(Bug.submission_date).label('first_seen'),
    ).join(Bug, Bug.species_id == Species.id)

    if search:
        likeq = f"%{search}%"
        species_query = species_query.filter(
            (Species.common_name.ilike(likeq)) |
            (Species.scientific_name.ilike(likeq)) |
            (Species.family.ilike(likeq)) |
            (Species.order.ilike(likeq))
        )

    species_rows = species_query.group_by(Species.id)\
        .order_by(func.count(Bug.id).desc()).all()

    # Build pioneer map: species_id → {username, bug_id, bug_nickname, date}
    pioneer_achievements = db.session.query(BugAchievement, Bug, _User)\
        .join(Bug, BugAchievement.bug_id == Bug.id)\
        .join(_User, Bug.user_id == _User.id)\
        .filter(BugAchievement.achievement_type == 'species_pioneer')\
        .all()
    pioneer_map: dict[int, dict] = {}
    for ach, bug, user in pioneer_achievements:
        if bug.species_id and bug.species_id not in pioneer_map:
            pioneer_map[bug.species_id] = {
                'username': user.username,
                'user_id': user.id,
                'bug_id': bug.id,
                'bug_nickname': bug.nickname,
                'date': ach.earned_date,
            }

    # Discovery leaderboard: users with most species_pioneer achievements
    from sqlalchemy import desc as _desc
    leader_rows = db.session.query(
        _User.id, _User.username, func.count(BugAchievement.id).label('discoveries')
    ).join(Bug, Bug.user_id == _User.id)\
     .join(BugAchievement, (BugAchievement.bug_id == Bug.id) & (BugAchievement.achievement_type == 'species_pioneer'))\
     .group_by(_User.id, _User.username)\
     .order_by(_desc('discoveries'))\
     .limit(10).all()
    discovery_leaders = [{'user_id': r.id, 'username': r.username, 'count': r.discoveries} for r in leader_rows]

    entries = []
    for row in species_rows:
        representative = Bug.query.filter_by(species_id=row.id)\
            .order_by(Bug.submission_date.desc()).first()
        entries.append({
            'id': row.id,
            'common_name': row.common_name,
            'scientific_name': row.scientific_name,
            'order': row.order,
            'family': row.family,
            'count': row.count,
            'last_seen': row.last_seen,
            'first_seen': row.first_seen,
            'image_path': representative.image_path if representative else None,
            'pioneer': pioneer_map.get(row.id),
        })

    # Location markers for all bugs with lat/lon
    location_markers = []
    for bug in Bug.query.filter(Bug.latitude.isnot(None), Bug.longitude.isnot(None)).all():
        species_name = (bug.species_info.common_name if bug.species_info else None) or bug.species or 'Unknown'
        location_markers.append({
            'lat': bug.latitude,
            'lng': bug.longitude,
            'nickname': bug.nickname,
            'species': species_name,
            'bug_id': bug.id,
        })

    total_species = len(entries)
    return render_template('insectidex.html',
                           species_entries=entries,
                           search=search,
                           discovery_leaders=discovery_leaders,
                           total_species=total_species,
                           location_markers=location_markers)


@bp.route('/insectidex/species/<int:species_id>')
@bp.route('/pokedex/species/<int:species_id>')
def insectidex_species(species_id):
    """Shortcut to list all bugs of a species via existing list view."""
    return redirect(url_for('bugs.list_bugs', species_id=species_id))



def _extract_traits_from_bug(bug):
    """Extract traits for LLM context"""
    traits = []
    
    if bug.species_info:
        species = bug.species_info
        if species.has_venom:
            traits.append('venomous')
        if species.has_pincers:
            traits.append('powerful pincers')
        if species.has_stinger:
            traits.append('stinger')
        if species.can_fly:
            traits.append('flight capable')
        if species.has_armor:
            traits.append('armored exoskeleton')
    
    return traits


@bp.route('/bug/<int:bug_id>/flag-classification', methods=['POST'])
@login_required
def flag_classification(bug_id):
    """Allow any authenticated user to dispute a bug's AI classification."""
    bug = db.get_or_404(Bug, bug_id)
    reason = (request.form.get('reason') or '').strip()
    suggested_species = (request.form.get('suggested_species') or '').strip() or None

    if not reason:
        flash('Please describe why you think the classification is wrong.', 'warning')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))

    existing = ClassificationFlag.query.filter_by(
        bug_id=bug_id, flagging_user_id=current_user.id
    ).first()
    if existing:
        flash('You have already flagged this bug\'s classification.', 'info')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))

    flag = ClassificationFlag(
        bug_id=bug_id,
        flagging_user_id=current_user.id,
        reason=reason,
        suggested_species=suggested_species,
        status='pending',
    )
    db.session.add(flag)
    db.session.commit()
    flash('Thanks — your classification dispute has been sent to the moderation team for review.', 'success')
    return redirect(url_for('bugs.view_bug', bug_id=bug_id))


@bp.route('/bug/<int:bug_id>/comment', methods=['POST'])
@login_required
def add_comment(bug_id):
    """Add a comment to a bug"""
    bug = db.get_or_404(Bug, bug_id)
    comment_text = request.form.get('comment')
    
    if not comment_text:
        flash('Comment cannot be empty', 'warning')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))
    
    comment = Comment(
        text=comment_text,
        bug_id=bug_id,
        user_id=current_user.id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    flash('Comment added!', 'success')
    return redirect(url_for('bugs.view_bug', bug_id=bug_id))


@bp.route('/bug/<int:bug_id>/lore', methods=['POST'])
@login_required
def add_lore(bug_id):
    """Add lore entry to a bug — restricted to the bug's owner and staff."""
    bug = db.get_or_404(Bug, bug_id)
    if bug.user_id != current_user.id and current_user.role not in ('MODERATOR', 'ADMIN', 'OWNER'):
        flash('You can only add lore to your own bugs.', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))
    lore_text = request.form.get('lore')

    if not lore_text:
        flash('Lore cannot be empty', 'warning')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))
    
    lore = BugLore(
        lore_text=lore_text,
        bug_id=bug_id,
        user_id=current_user.id
    )
    
    db.session.add(lore)
    from app.services.achievements import award_lore_participation
    award_lore_participation(bug)
    db.session.commit()
    
    flash('Lore added to the legend!', 'success')
    return redirect(url_for('bugs.view_bug', bug_id=bug_id))


@bp.route('/comment/<int:comment_id>/upvote', methods=['POST'])
@login_required
def upvote_comment(comment_id):
    comment = db.get_or_404(Comment, comment_id)
    existing = CommentVote.query.filter_by(comment_id=comment.id, user_id=current_user.id).first()
    if existing:
        return jsonify({'success': True, 'upvotes': comment.upvotes, 'already_voted': True}), 200

    vote = CommentVote(comment_id=comment.id, user_id=current_user.id)
    comment.upvotes = (comment.upvotes or 0) + 1
    db.session.add(vote)
    db.session.commit()
    return jsonify({'success': True, 'upvotes': comment.upvotes}), 200


@bp.route('/lore/<int:lore_id>/upvote', methods=['POST'])
@login_required
def upvote_lore(lore_id):
    lore = db.get_or_404(BugLore, lore_id)
    existing = BugLoreVote.query.filter_by(lore_id=lore.id, user_id=current_user.id).first()
    if existing:
        return jsonify({'success': True, 'upvotes': lore.upvotes, 'already_voted': True}), 200

    vote = BugLoreVote(lore_id=lore.id, user_id=current_user.id)
    lore.upvotes = (lore.upvotes or 0) + 1
    db.session.add(vote)
    db.session.commit()
    return jsonify({'success': True, 'upvotes': lore.upvotes}), 200

# API endpoint for pre-upload verification
@bp.route('/api/bug/pre-verify', methods=['POST'])
@login_required
def pre_verify_bug():
    """
    Pre-verify bug before full submission
    Allows frontend to show issues before user fills out form
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image provided'}), 400
    
    file = request.files['image']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    # Save temporary file
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_filename = f"preview_{current_user.id}_{timestamp}_{filename}"
    temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], temp_filename)
    file.save(temp_path)
    
    try:
        # Run verification
        from app.services.vision_service import VisionService
        
        vision = VisionService()
        vision_result = vision.verify_bug_image(temp_path)
        duplicate_check = vision.check_duplicate_bug(temp_path, current_user.id)
        
        # Cleanup temp file
        os.remove(temp_path)
        
        # Build response
        response = {
            'is_bug': vision_result.get('is_bug'),
            'confidence': vision_result.get('confidence'),
            'quality_score': vision_result.get('quality_score'),
            'identified_species': vision_result.get('identified_species'),
            'common_name': vision_result.get('common_name'),
            'issues': [],
            'warnings': []
        }
        
        # Check issues
        if not vision_result.get('is_bug'):
            response['issues'].append('This does not appear to be a bug')
        
        if vision_result.get('confidence', 0) < 0.8:
            response['issues'].append(f"Confidence too low: {vision_result['confidence']:.0%}")
        
        if vision_result.get('quality_score', 0) < 0.6:
            response['warnings'].append('Image quality could be improved')
        
        for issue in vision_result.get('quality_issues', []):
            response['warnings'].append(f'Quality issue: {issue}')
        
        if duplicate_check.get('is_duplicate'):
            response['issues'].append(
                f"This appears to be a duplicate of '{duplicate_check['duplicate_bug_name']}'"
            )
        
        response['can_submit'] = len(response['issues']) == 0
        
        return jsonify(response), 200
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return jsonify({'error': str(e)}), 500


# Admin route to review flagged bugs
@bp.route('/admin/review-bugs')
@login_required
@require_role(UserRole.MODERATOR)
def review_bugs():
    """View bugs that need manual review"""
    
    pending_bugs = Bug.query.filter_by(
        requires_manual_review=True
    ).order_by(Bug.submission_date.desc()).all()
    
    return render_template('admin/review_bugs.html', bugs=pending_bugs)


@bp.route('/admin/bug/<int:bug_id>/approve', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def approve_bug(bug_id):
    """Approve a bug after manual review"""
    bug = db.get_or_404(Bug, bug_id)
    
    bug.requires_manual_review = False
    bug.is_verified = True
    bug.review_notes = request.form.get('notes', '')
    
    db.session.commit()
    
    
    flash(f'{bug.nickname} approved!', 'success')
    return redirect(url_for('bugs.review_bugs'))


@bp.route('/admin/bug/<int:bug_id>/reject', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def reject_bug(bug_id):
    """Reject a bug after manual review"""
    
    bug = db.get_or_404(Bug, bug_id)
    
    bug.review_notes = request.form.get('notes', 'Rejected by moderator')
    
    db.session.commit()
    
    flash(f'{bug.nickname} rejected', 'info')
    return redirect(url_for('bugs.review_bugs'))


@bp.route('/admin/bug/<int:bug_id>/correct_species', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def correct_bug_species(bug_id):
    """Allow admins/mods to correct the species assignment for a bug."""
    bug = db.get_or_404(Bug, bug_id)

    species_id = request.form.get('species_id')
    common_name = request.form.get('common_name')
    scientific_name = request.form.get('scientific_name')

    if species_id:
        try:
            sp = db.session.get(Species, int(species_id))
            if sp:
                bug.species_id = sp.id
                bug.common_name = sp.common_name
                bug.scientific_name = sp.scientific_name
        except Exception:
            flash('Invalid species selected', 'warning')
    else:
        # Allow freeform correction
        if common_name:
            bug.common_name = common_name
        if scientific_name:
            bug.scientific_name = scientific_name

    db.session.commit()
    flash('Species information updated.', 'success')
    return redirect(url_for('bugs.view_bug', bug_id=bug.id))


_VALID_ATTACK_TYPES = {
    'piercing', 'crushing', 'slashing', 'venom', 'chemical',
    'grappling', 'sonic', 'electric', 'neutral',
}
_VALID_DEFENSE_TYPES = {
    'hard_shell', 'segmented_armor', 'evasive', 'hairy_spiny', 'toxic_skin',
    'thick_hide', 'unarmored', 'regenerative', 'bioluminescent',
}


@bp.route('/admin/bug/<int:bug_id>/set_typing', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def set_bug_typing(bug_id):
    """Allow admins/mods to set or update a bug's attack/defense typing."""
    bug = db.get_or_404(Bug, bug_id)

    attack_type = request.form.get('attack_type', '').strip() or None
    defense_type = request.form.get('defense_type', '').strip() or None

    if attack_type and attack_type not in _VALID_ATTACK_TYPES:
        flash(f'Invalid attack type: {attack_type}', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))
    if defense_type and defense_type not in _VALID_DEFENSE_TYPES:
        flash(f'Invalid defense type: {defense_type}', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))

    bug.attack_type = attack_type
    bug.defense_type = defense_type
    db.session.commit()
    flash('Combat typing updated.', 'success')
    return redirect(url_for('bugs.view_bug', bug_id=bug.id))


# ── Admin rejected-submission review queue ────────────────────────────────────

@bp.route('/admin/review-rejected')
@login_required
@require_role(UserRole.MODERATOR)
def review_rejected_submissions():
    submissions = (
        RejectedSubmission.query
        .filter_by(status='pending')
        .order_by(RejectedSubmission.submitted_at.desc())
        .all()
    )
    return render_template('admin/review_rejected.html', submissions=submissions)


@bp.route('/admin/rejected/<int:submission_id>/dismiss', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def dismiss_rejected_submission(submission_id):
    sub = db.get_or_404(RejectedSubmission, submission_id)
    sub.status = 'dismissed'
    sub.admin_notes = request.form.get('admin_notes', '')
    sub.reviewed_at = datetime.utcnow()
    sub.reviewed_by_id = current_user.id
    db.session.commit()
    # Clean up stored image
    if sub.image_path:
        img_full = os.path.join(current_app.config['UPLOAD_FOLDER'], sub.image_path)
        try:
            if os.path.exists(img_full):
                os.remove(img_full)
        except Exception:
            pass
    flash('Submission dismissed.', 'info')
    return redirect(url_for('bugs.review_rejected_submissions'))


@bp.route('/admin/rejected/<int:submission_id>/approve', methods=['POST'])
@login_required
@require_role(UserRole.MODERATOR)
def approve_rejected_submission(submission_id):
    """Admin manually approves a previously-rejected submission."""
    sub = db.get_or_404(RejectedSubmission, submission_id)
    if sub.status != 'pending':
        flash('Already reviewed.', 'warning')
        return redirect(url_for('bugs.review_rejected_submissions'))

    # Move image from review folder to normal upload folder
    if not sub.image_path:
        flash('No image on file — cannot approve.', 'danger')
        return redirect(url_for('bugs.review_rejected_submissions'))

    review_full = os.path.join(current_app.config['UPLOAD_FOLDER'], sub.image_path)
    if not os.path.exists(review_full):
        flash('Image file missing — cannot approve.', 'danger')
        return redirect(url_for('bugs.review_rejected_submissions'))

    final_filename = f"approved_{sub.user_id}_{os.path.basename(sub.image_path)}"
    final_path = os.path.join(current_app.config['UPLOAD_FOLDER'], final_filename)
    os.rename(review_full, final_path)

    from app.services.tier_system import LLMStatGenerator, TierSystem, TIER_DEFINITIONS
    import imagehash as _ih

    candidate_hash = _ih.average_hash(Image.open(final_path))

    bug = Bug(
        nickname=sub.nickname,
        description=sub.description,
        location_found=sub.location_found,
        image_path=final_filename,
        user_id=sub.user_id,
        vision_verified=True,
        vision_confidence=0.5,
        requires_manual_review=False,
        image_hash=str(candidate_hash),
    )
    db.session.add(bug)
    db.session.flush()

    stat_generator = LLMStatGenerator()
    stats = stat_generator.generate_stats_with_llm({'common_name': sub.nickname or 'Unknown'})
    bug.attack = stats.get('attack', 5)
    bug.defense = stats.get('defense', 5)
    bug.speed = stats.get('speed', 5)
    bug.lethality = stats.get('lethality', 50)
    bug.grip = stats.get('grip', 50)
    bug.cunning = stats.get('cunning', 50)
    bug.special_ability = stats.get('special_ability')
    bug.stats_generation_method = 'admin_override'
    bug.stats_generated = True
    bug.tier = TierSystem.assign_tier(bug)
    bug.condition = 'alive'
    bug.generate_flair()

    from app.services.job_queue import enqueue_bug_enrichment
    enqueue_bug_enrichment(bug, final_path)

    sub.status = 'approved'
    sub.admin_notes = request.form.get('admin_notes', '')
    sub.reviewed_at = datetime.utcnow()
    sub.reviewed_by_id = current_user.id
    db.session.commit()

    flash(f'Submission approved — bug #{bug.id} created.', 'success')
    return redirect(url_for('bugs.review_rejected_submissions'))
