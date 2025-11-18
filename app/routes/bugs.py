"""
Complete Enhanced Bug Submission Route
Integrates: Vision verification, duplicate detection, LLM stats, tier assignment
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Bug, Species, Comment, BugLore
from app.services.vision_service import comprehensive_bug_verification
from app.services.tier_system import LLMStatGenerator, TierSystem, assign_tier_and_generate_stats
from app.services.taxonomy import TaxonomyService
import os
from datetime import datetime
import imagehash
from PIL import Image

bp = Blueprint('bugs', __name__)

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

    query = Bug.query

    if mine and current_user.is_authenticated:
        query = query.filter(Bug.user_id == current_user.id)

    if tier:
        query = query.filter(Bug.tier == tier)

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

    return render_template('bug_list.html', bugs=bugs, tiers=tiers, active_filters={'search': search, 'tier': tier, 'mine': mine})

@bp.route('/bug/<int:bug_id>')
def view_bug(bug_id):
    """View individual bug profile"""
    bug = Bug.query.get_or_404(bug_id)
    comments = Comment.query.filter_by(bug_id=bug_id)\
        .order_by(Comment.created_at.desc()).all()
    lore = BugLore.query.filter_by(bug_id=bug_id)\
        .order_by(BugLore.upvotes.desc()).all()
    
    return render_template('bug_profile.html', 
                         bug=bug, 
                         comments=comments,
                         lore=lore)

def handle_submission():
    """Process bug submission with LLM-controlled classification"""
    
    # Get form data
    nickname = request.form.get('nickname')
    description = request.form.get('description')
    location_found = request.form.get('location_found')
    user_species_guess = request.form.get('user_species_guess')

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
    file.save(temp_path)
    
    try:
        # LLM Classification
        from app.services.bug_classifier import classify_bug_submission
        
        classification = classify_bug_submission(
            image_path=temp_path,
            user_id=current_user.id,
            nickname=nickname,
            description=description,
            user_species_guess=user_species_guess
        )
        
        # Check if LLM approved
        if not classification.approved:
            os.remove(temp_path)
            flash('❌ Submission Rejected', 'danger')
            for reason in classification.rejection_reasons:
                flash(f'• {reason}', 'warning')
            
            # Show user's guess feedback if provided
            if classification.user_guess_feedback:
                flash(f'About your identification: {classification.user_guess_feedback}', 'info')
            
            return redirect(url_for('bugs.submit_bug'))
        
        # LLM APPROVED - continue with submission
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
            
            image_hash=str(imagehash.average_hash(Image.open(final_path))),
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
        bug.special_ability = stats.get('special_ability')
        bug.stats_generation_method = 'llm_contextual'
        bug.stats_generated = True
        
        # Assign tier
        bug.tier = TierSystem.assign_tier(bug)
        tier_info = TIER_DEFINITIONS.get(bug.tier, {})
        
        # Generate visual lore
        try:
            from app.services.visual_lore_generator import VisualLoreAnalyzer
            lore_analyzer = VisualLoreAnalyzer()
            lore_analyzer.apply_visual_lore_to_bug(bug, final_path)
        except Exception as e:
            print(f"Visual lore generation failed: {e}")
        
        bug.generate_flair()
        db.session.commit()
        
        # Success messages
        if user_species_guess:
            if classification.user_guess_matches:
                flash(f'✅ Excellent identification! {classification.user_guess_feedback}', 'success')
            elif classification.user_guess_matches is False:
                flash(f'ℹ️ {classification.user_guess_feedback}', 'info')
        
        flash(f'✅ {nickname} approved and entered the arena!', 'success')
        flash(f'{tier_info.get("icon", "")} {tier_info.get("name", bug.tier)}', 'info')
        
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


@bp.route('/bug/<int:bug_id>/comment', methods=['POST'])
@login_required
def add_comment(bug_id):
    """Add a comment to a bug"""
    bug = Bug.query.get_or_404(bug_id)
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
    """Add lore entry to a bug"""
    bug = Bug.query.get_or_404(bug_id)
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
    db.session.commit()
    
    flash('Lore added to the legend!', 'success')
    return redirect(url_for('bugs.view_bug', bug_id=bug_id))

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
        # Cleanup on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return jsonify({'error': str(e)}), 500


# Admin route to review flagged bugs
@bp.route('/admin/review-bugs')
@login_required
def review_bugs():
    """View bugs that need manual review"""
    # TODO: Add admin check
    
    pending_bugs = Bug.query.filter_by(
        requires_manual_review=True
    ).order_by(Bug.submission_date.desc()).all()
    
    return render_template('admin/review_bugs.html', bugs=pending_bugs)


@bp.route('/admin/bug/<int:bug_id>/approve', methods=['POST'])
@login_required
def approve_bug(bug_id):
    """Approve a bug after manual review"""
    # TODO: Add admin check
    
    bug = Bug.query.get_or_404(bug_id)
    
    bug.requires_manual_review = False
    bug.is_verified = True
    bug.review_notes = request.form.get('notes', '')
    
    db.session.commit()
    
    
    flash(f'{bug.nickname} approved!', 'success')
    return redirect(url_for('bugs.review_bugs'))


@bp.route('/admin/bug/<int:bug_id>/reject', methods=['POST'])
@login_required
def reject_bug(bug_id):
    """Reject a bug after manual review"""
    # TODO: Add admin check
    
    bug = Bug.query.get_or_404(bug_id)
    
    bug.review_notes = request.form.get('notes', 'Rejected by moderator')
    
    # Optional: Delete or mark as rejected
    # For now, just flag it
    
    db.session.commit()
    
    flash(f'{bug.nickname} rejected', 'info')
    return redirect(url_for('bugs.review_bugs'))