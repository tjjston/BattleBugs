"""
Complete Enhanced Bug Submission Route
Integrates: Vision verification, duplicate detection, LLM stats, tier assignment
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Bug, Species, Comment, BugLore, CommentVote, BugLoreVote, Job, BugRival, ClassificationFlag, BlockedImageHash, RejectedSubmission, User
from sqlalchemy import func
from app.services.vision_service import comprehensive_bug_verification
from app.services.tier_system import LLMStatGenerator, TierSystem, assign_tier_and_generate_stats
from app.services.taxonomy import TaxonomyService
from app.services.permission_system import require_role, UserRole
from app.services.economy import (
    InsufficientCurrencyError,
    spend_currency,
)
import json
import os
from datetime import datetime, timezone
import imagehash
from PIL import Image


bp = Blueprint('bugs', __name__)


def _crop_and_enhance_bug_image(image_path: str) -> None:
    """
    Detect the bug's bounding box via Poseidon (if available), crop to it,
    apply mild contrast + sharpness enhancement, and save back in place.
    Falls back to a center-weighted square crop when Poseidon is unavailable.
    """
    from PIL import ImageEnhance
    try:
        img = Image.open(image_path)
    except Exception:
        return

    if img.mode not in ('RGB',):
        img = img.convert('RGB')

    orig_w, orig_h = img.size
    cropped = None

    # ── Poseidon detection crop ───────────────────────────────────────────
    try:
        from app.services.poseidon_pipeline import PoseidonPipeline
        pipeline = PoseidonPipeline()
        if pipeline.capabilities().get('detect'):
            boxes = pipeline.detect(image_path)
            real = [b for b in boxes if not (b.x1 == 0 and b.y1 == 0 and b.x2 == 1 and b.y2 == 1)]
            if real:
                best = max(real, key=lambda b: b.confidence)
                pad_x = (best.x2 - best.x1) * 0.18
                pad_y = (best.y2 - best.y1) * 0.18
                x1 = int(max(0.0, best.x1 - pad_x) * orig_w)
                y1 = int(max(0.0, best.y1 - pad_y) * orig_h)
                x2 = int(min(1.0, best.x2 + pad_x) * orig_w)
                y2 = int(min(1.0, best.y2 + pad_y) * orig_h)
                if (x2 - x1) >= 80 and (y2 - y1) >= 80:
                    cropped = img.crop((x1, y1, x2, y2))
    except Exception:
        pass

    if cropped is None:
        # ── Center-biased square crop (slightly above centre for most bug photos) ──
        side = min(orig_w, orig_h)
        left = (orig_w - side) // 2
        top = max(0, int((orig_h - side) * 0.40))
        cropped = img.crop((left, top, left + side, top + side))

    # Resize to a standard profile-pic size (max 900 px on the long edge)
    cropped.thumbnail((900, 900), Image.LANCZOS)

    # Subtle enhancement — boost contrast + sharpness so the bug pops
    cropped = ImageEnhance.Contrast(cropped).enhance(1.15)
    cropped = ImageEnhance.Sharpness(cropped).enhance(1.35)

    ext = os.path.splitext(image_path)[1].lower()
    save_fmt = 'PNG' if ext == '.png' else 'JPEG'
    save_kw = {'optimize': True} if save_fmt == 'PNG' else {'quality': 92, 'optimize': True}
    cropped.save(image_path, save_fmt, **save_kw)
    current_app.logger.info("Bug image cropped/enhanced → %s (%dx%d)", image_path, *cropped.size)


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

    # Filters
    search = request.args.get('search', type=str)
    tier = request.args.get('tier', type=str)
    mine = request.args.get('mine', default=0, type=int)
    species_id = request.args.get('species_id', type=int)
    condition = request.args.get('condition', type=str)
    sort_by = request.args.get('sort_by', default='newest', type=str)
    active_only = request.args.get('active_only', default=0, type=int)
    attack_type = request.args.get('attack_type', type=str)
    defense_type = request.args.get('defense_type', type=str)

    query = Bug.query

    if mine and current_user.is_authenticated:
        query = query.filter(Bug.user_id == current_user.id)

    if tier:
        query = query.filter(Bug.tier == tier)

    if species_id:
        query = query.filter(Bug.species_id == species_id)

    if condition == 'alive':
        query = query.filter(Bug.condition == 'alive')
    elif condition == 'dead':
        query = query.filter(Bug.is_zombug == True)
    elif condition == 'damaged':
        query = query.filter(Bug.condition.in_(['damaged', 'damaged_wings', 'damaged_legs', 'squashed']))

    if active_only:
        query = query.filter(Bug.is_retired != True)

    if attack_type:
        query = query.filter(Bug.attack_type == attack_type)

    if defense_type:
        query = query.filter(Bug.defense_type == defense_type)

    if search:
        likeq = f"%{search}%"
        query = query.filter(
            (Bug.nickname.ilike(likeq)) |
            (Bug.common_name.ilike(likeq)) |
            (Bug.scientific_name.ilike(likeq))
        )

    if sort_by == 'wins':
        query = query.order_by(Bug.wins.desc())
    elif sort_by == 'power':
        query = query.order_by(
            (Bug.attack + Bug.defense + Bug.speed).desc()
        )
    elif sort_by == 'winrate':
        query = query.filter((Bug.wins + Bug.losses) >= 1)\
            .order_by(((Bug.wins * 100.0) / (Bug.wins + Bug.losses)).desc())
    else:
        query = query.order_by(Bug.submission_date.desc())

    bugs = query.paginate(page=page, per_page=current_app.config.get('BUGS_PER_PAGE', 20), error_out=False)

    tiers = db.session.query(Bug.tier).distinct().all()
    tiers = [t[0] for t in tiers if t[0]]

    species_filter_name = None
    if species_id:
        _sp = db.session.get(Species, species_id)
        if _sp:
            species_filter_name = _sp.common_name or _sp.scientific_name

    return render_template('bug_list.html', bugs=bugs, tiers=tiers,
                           active_filters={
                               'search': search, 'tier': tier, 'mine': mine,
                               'species_id': species_id, 'condition': condition,
                               'sort_by': sort_by, 'active_only': active_only,
                               'attack_type': attack_type, 'defense_type': defense_type,
                           },
                           species_filter_name=species_filter_name)

@bp.route('/bug/<int:bug_id>')
def view_bug(bug_id):
    """View individual bug profile"""
    bug = db.get_or_404(Bug, bug_id)
    comments = Comment.query.filter_by(bug_id=bug_id)\
        .order_by(Comment.created_at.desc()).all()
    lore = BugLore.query.filter_by(bug_id=bug_id)\
        .order_by(BugLore.upvotes.desc()).all()
    jobs = Job.query.filter(func.json_extract(Job.payload_json, '$.bug_id') == bug.id)\
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

    species_facts_sample = _sample_species_facts(bug, count=3)

    ability_effect = None
    if bug.ability_slug:
        from app.services import ability_catalog as _ac
        a = _ac.get(bug.ability_slug)
        if a:
            ability_effect = {
                'slug': a.slug,
                'name': a.name,
                'description': a.description,
                'effect': _ac.describe_effect(a),
            }

    return render_template('bug_profile.html',
                         bug=bug,
                         comments=comments,
                         lore=lore,
                         jobs=jobs,
                         rivals=rivals,
                         show_exact_stats=show_exact_stats,
                         species_facts_sample=species_facts_sample,
                         ability_effect=ability_effect)


def _sample_species_facts(bug, count=3):
    """Return up to `count` random facts from the bug's species fact pool."""
    if not bug.species_info or not bug.species_info.interesting_facts:
        return []
    try:
        pool = json.loads(bug.species_info.interesting_facts) or []
    except Exception:
        return []
    pool = [f for f in pool if isinstance(f, str) and f.strip()]
    if not pool:
        return []
    import random as _r
    _r.shuffle(pool)
    return pool[:count]

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

    file_size = os.path.getsize(temp_path)
    current_app.logger.info(
        "SUBMIT [user=%s] file saved: %s (%.1f KB)",
        current_user.id, temp_path, file_size / 1024,
    )

    try:
        # --- Duplicate / blocked image hash check (before LLM call to save quota) ---
        candidate_hash = imagehash.average_hash(Image.open(temp_path))
        h_str = str(candidate_hash)
        current_app.logger.debug("SUBMIT [user=%s] image hash: %s", current_user.id, h_str)

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

        current_app.logger.info("SUBMIT [user=%s] starting LLM classification", current_user.id)
        classification = classify_bug_submission(
            image_path=temp_path,
            user_id=current_user.id,
            nickname=nickname,
            description=description,
            user_species_guess=user_species_guess
        )
        current_app.logger.info(
            "SUBMIT [user=%s] classification done — approved=%s provider=%s confidence=%.2f reasons=%s",
            current_user.id, classification.approved, classification.llm_provider,
            classification.confidence, classification.rejection_reasons,
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

        # Crop to subject + enhance — non-fatal if Poseidon is down
        try:
            _crop_and_enhance_bug_image(final_path)
        except Exception as _ce:
            current_app.logger.warning("Image crop/enhance skipped: %s", _ce)

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

            # Enrich new or un-enriched species with photo + facts in background
            if species_info and species_info.id and (
                not species_info.image_url or not species_info.interesting_facts
            ):
                import threading as _threading
                _species_id = species_info.id
                _app = current_app._get_current_object()
                def _enrich_bg(app, sid):
                    try:
                        with app.app_context():
                            TaxonomyService().enrich_species(sid)
                    except Exception:
                        pass
                _threading.Thread(target=_enrich_bg, args=(_app, _species_id), daemon=True).start()

        # Second hash check: re-validate uniqueness immediately before writing,
        # narrowing the race window that exists between the pre-LLM check and now.
        for (existing_h,) in db.session.query(Bug.image_hash).filter(Bug.image_hash.isnot(None)).all():
            try:
                if imagehash.hex_to_hash(existing_h) - candidate_hash <= 8:
                    os.remove(final_path)
                    db.session.rollback()
                    flash('This bug image has already been submitted.', 'danger')
                    return redirect(url_for('bugs.submit_bug'))
            except Exception:
                continue

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
        
        # Assign fast fallback stats immediately so submission never blocks on the LLM.
        # A STAT_RECALC_JOB queued below will upgrade these to LLM-generated values.
        from app.services.tier_system import _fallback_stats, TierSystem, TIER_DEFINITIONS

        bug_info = {
            'scientific_name': bug.scientific_name,
            'common_name': bug.common_name,
            'size_mm': bug.species_info.average_size_mm if bug.species_info else None,
            'traits': _extract_traits_from_bug(bug),
            'species_info': bug.species_info.to_dict() if bug.species_info else None
        }

        stats = _fallback_stats(bug_info)
        current_app.logger.info(
            "SUBMIT [user=%s] fallback stats — ATK=%s DEF=%s SPD=%s (LLM recalc queued)",
            current_user.id, stats.get('attack'), stats.get('defense'), stats.get('speed'),
        )
        bug.attack = stats['attack']
        bug.defense = stats['defense']
        bug.speed = stats['speed']
        bug.lethality = stats.get('lethality', 50)
        bug.grip = stats.get('grip', 50)
        bug.cunning = stats.get('cunning', 50)
        bug.special_ability = stats.get('special_ability')
        bug.stats_generation_method = 'fallback_pending_llm'
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
        jobs = enqueue_bug_enrichment(bug, final_path)
        current_app.logger.info(
            "SUBMIT [user=%s] bug#%s created — tier=%s tier_assigned=%s enrichment_jobs=%s image=%s",
            current_user.id, bug.id, bug.tier, bug.enrichment_status,
            [j.id for j in jobs], final_path,
        )
        
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

        # Increment owner's bug counter
        current_user.bugs_submitted = (current_user.bugs_submitted or 0) + 1
        db.session.commit()

        # NOW redirect (bug.id exists!)
        return redirect(url_for('bugs.view_bug', bug_id=bug.id, _celebrate='submit'))
        
    except Exception as e:
        current_app.logger.error(
            "SUBMIT [user=%s] FAILED at step unknown — %s",
            current_user.id, e, exc_info=True,
        )
        if os.path.exists(temp_path):
            os.remove(temp_path)
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
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


@bp.route('/bug/<int:bug_id>/recalc', methods=['POST'])
@login_required
def recalc_bug_stats(bug_id):
    """Admin-only: auto-apply LLM-recalculated stats immediately (no user review)."""
    bug = db.get_or_404(Bug, bug_id)
    if current_user.role not in ('ADMIN', 'OWNER'):
        flash('Only admins can recalculate stats.', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))
    try:
        generator = LLMStatGenerator()
        generator.regenerate_stats_for_bug(bug)
        flash('Stats recalculated and applied by the lab.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Stat recalculation failed: {e}', 'danger')
    return redirect(url_for('bugs.view_bug', bug_id=bug.id))


@bp.route('/bug/<int:bug_id>/recalc/deny', methods=['POST'])
@login_required
def deny_recalc_bug_stats(bug_id):
    bug = db.get_or_404(Bug, bug_id)
    flash('No changes applied.', 'info')
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
        Species.image_url,
        Species.interesting_facts,
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

    # Kick a background re-enrichment for species missing an iNat image so
    # the field-guide view backfills over time. We don't block the request.
    _missing_img_ids = [r.id for r in species_rows if not r.image_url][:8]
    if _missing_img_ids:
        import threading as _threading
        _app = current_app._get_current_object()
        def _bg_enrich(app, ids):
            try:
                with app.app_context():
                    from app.services.taxonomy import TaxonomyService
                    svc = TaxonomyService()
                    for sid in ids:
                        try:
                            svc.enrich_species(sid)
                        except Exception:
                            pass
            except Exception:
                pass
        _threading.Thread(target=_bg_enrich, args=(_app, _missing_img_ids), daemon=True).start()

    entries = []
    for row in species_rows:
        representative = Bug.query.filter_by(species_id=row.id)\
            .order_by(Bug.submission_date.desc()).first()
        facts = []
        if row.interesting_facts:
            try:
                import json as _j
                facts = _j.loads(row.interesting_facts)[:3]
            except Exception:
                pass
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
            'species_image_url': row.image_url,
            'facts': facts,
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
    """Species detail: taxonomy header tile + all arena bugs, newest first."""
    import json as _json
    species = db.get_or_404(Species, species_id)

    bugs = Bug.query.filter_by(species_id=species_id)\
        .order_by(Bug.submission_date.desc()).all()

    facts = []
    if species.interesting_facts:
        try:
            facts = _json.loads(species.interesting_facts)
        except Exception:
            pass

    # Pioneer for this species
    pioneer = None
    try:
        ach = BugAchievement.query\
            .join(Bug, BugAchievement.bug_id == Bug.id)\
            .filter(Bug.species_id == species_id,
                    BugAchievement.achievement_type == 'species_pioneer')\
            .order_by(BugAchievement.earned_date.asc()).first()
        if ach:
            pioneer = {'bug': ach.bug, 'user': ach.bug.owner, 'date': ach.earned_date}
    except Exception:
        pass

    return render_template('insectidex_species.html',
                           species=species, bugs=bugs,
                           facts=facts, pioneer=pioneer)



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
    sub.reviewed_at = datetime.now(timezone.utc)
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
    sub.reviewed_at = datetime.now(timezone.utc)
    sub.reviewed_by_id = current_user.id
    # Increment owner's bug counter
    owner = db.session.get(User, sub.user_id)
    if owner:
        owner.bugs_submitted = (owner.bugs_submitted or 0) + 1
    db.session.commit()

    flash(f'Submission approved — bug #{bug.id} created.', 'success')
    return redirect(url_for('bugs.review_rejected_submissions'))


@bp.route('/bug/<int:bug_id>/release', methods=['POST'])
@login_required
def release_bug(bug_id):
    bug = db.get_or_404(Bug, bug_id)

    is_owner = bug.user_id == current_user.id
    is_staff = current_user.role in ('ADMIN', 'OWNER')
    if not (is_owner or is_staff):
        flash('Only the bug owner or an admin can release a bug.', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))

    bug_name = bug.nickname
    image_path = bug.image_path

    try:
        _do_release_bug(bug)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error("Release bug#%s failed: %s", bug_id, e, exc_info=True)
        flash(f'Could not release bug: {e}', 'danger')
        return redirect(url_for('bugs.view_bug', bug_id=bug_id))

    if image_path:
        full_path = os.path.join(current_app.config['UPLOAD_FOLDER'], image_path)
        try:
            if os.path.exists(full_path):
                os.remove(full_path)
        except Exception:
            pass

    current_app.logger.info("RELEASE bug '%s' (id=%s) by user=%s", bug_name, bug_id, current_user.id)
    flash(f'{bug_name} has been released back into the wild.', 'success')
    return redirect(url_for('bugs.list_bugs'))


def _do_release_bug(bug):
    """Delete a bug and all records that reference it."""
    from app.models import (
        Battle, BugRival, ClassificationFlag, TournamentApplication,
        TournamentMatch, SeasonMatch, SeasonRegistration, Job,
        TierChampionship, TierRanking, TitleFight, TitleBid,
        ContenderCallout, Tournament,
    )
    from sqlalchemy import or_

    bug_id = bug.id

    # Null out nullable FK references that point to this bug
    db.session.query(TierChampionship).filter_by(champion_bug_id=bug_id).update(
        {'champion_bug_id': None}, synchronize_session='fetch'
    )
    db.session.query(TitleFight).filter_by(challenger_bug_id=bug_id).update(
        {'challenger_bug_id': None}, synchronize_session='fetch'
    )
    db.session.query(Tournament).filter_by(winner_id=bug_id).update(
        {'winner_id': None}, synchronize_session='fetch'
    )

    # Delete records with non-nullable bug_id FKs
    ClassificationFlag.query.filter_by(bug_id=bug_id).delete(synchronize_session='fetch')
    TournamentApplication.query.filter_by(bug_id=bug_id).delete(synchronize_session='fetch')
    SeasonRegistration.query.filter_by(bug_id=bug_id).delete(synchronize_session='fetch')
    TierRanking.query.filter_by(bug_id=bug_id).delete(synchronize_session='fetch')
    TitleBid.query.filter_by(bug_id=bug_id).delete(synchronize_session='fetch')
    ContenderCallout.query.filter(
        or_(ContenderCallout.challenger_bug_id == bug_id,
            ContenderCallout.target_bug_id == bug_id)
    ).delete(synchronize_session='fetch')
    BugRival.query.filter(
        or_(BugRival.bug1_id == bug_id, BugRival.bug2_id == bug_id)
    ).delete(synchronize_session='fetch')

    # TournamentMatch rows referencing this bug (FKs are nullable — just delete them)
    TournamentMatch.query.filter(
        or_(
            TournamentMatch.bug1_id == bug_id,
            TournamentMatch.bug2_id == bug_id,
            TournamentMatch.winner_id == bug_id,
        )
    ).delete(synchronize_session='fetch')

    # Battles involving this bug (bug1_id / bug2_id are NOT NULL)
    affected_battles = db.session.query(Battle.id).filter(
        or_(Battle.bug1_id == bug_id, Battle.bug2_id == bug_id)
    ).all()
    battle_ids = [r.id for r in affected_battles]

    if battle_ids:
        # Null out SeasonMatch.battle_id references to these battles before deleting them
        SeasonMatch.query.filter(
            SeasonMatch.battle_id.in_(battle_ids)
        ).update({'battle_id': None}, synchronize_session='fetch')
        Battle.query.filter(Battle.id.in_(battle_ids)).delete(synchronize_session='fetch')

    # SeasonMatch rows referencing this bug (bug1_id / bug2_id are NOT NULL)
    SeasonMatch.query.filter(
        or_(SeasonMatch.bug1_id == bug_id, SeasonMatch.bug2_id == bug_id)
    ).delete(synchronize_session='fetch')

    # Background jobs enqueued for this bug — filter in Python to avoid json_extract compat issues
    all_pending = Job.query.filter(Job.status.in_(['pending', 'processing'])).all()
    for job in all_pending:
        try:
            import json as _json
            payload = _json.loads(job.payload_json or '{}')
            if payload.get('bug_id') == bug_id:
                db.session.delete(job)
        except Exception:
            pass

    db.session.delete(bug)  # cascade: comments, lore, achievements
    db.session.commit()

