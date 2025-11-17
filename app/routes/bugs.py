"""
Complete Enhanced Bug Submission Route
Integrates: Vision verification, duplicate detection, LLM stats, tier assignment
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Bug, Species
from app.services.vision_service import comprehensive_bug_verification
from app.services.tier_system import LLMStatGenerator, TierSystem, assign_tier_and_generate_stats
from app.services.taxonomy import TaxonomyService
import os
from datetime import datetime
import imagehash
from PIL import Image

bp = Blueprint('bugs_advanced', __name__)

@bp.route('/bug/submit-advanced', methods=['GET', 'POST'])
@login_required
def submit_bug_advanced():
    """
    Advanced bug submission with full verification pipeline
    """
    if request.method == 'POST':
        return handle_advanced_submission()
    
    return render_template('submit_bug_advanced.html')


def handle_advanced_submission():
    """Process advanced bug submission"""
    
    # Step 1: Get form data
    nickname = request.form.get('nickname')
    description = request.form.get('description')
    location_found = request.form.get('location_found')
    
    # Step 2: Handle image upload
    if 'image' not in request.files:
        flash('No image provided', 'danger')
        return redirect(url_for('bugs_advanced.submit_bug_advanced'))
    
    file = request.files['image']
    
    if file.filename == '':
        flash('No image selected', 'danger')
        return redirect(url_for('bugs_advanced.submit_bug_advanced'))
    
    if not allowed_file(file.filename):
        flash('Invalid file type', 'danger')
        return redirect(url_for('bugs_advanced.submit_bug_advanced'))
    
    # Save temporary file for verification
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_filename = f"temp_{current_user.id}_{timestamp}_{filename}"
    temp_path = os.path.join(current_app.config['UPLOAD_FOLDER'], temp_filename)
    file.save(temp_path)
    
    try:
        # Step 3: Comprehensive verification
        verification_result = comprehensive_bug_verification(temp_path, current_user.id)
        
        # Step 4: Check if approved
        if not verification_result['approved']:
            # Cleanup temp file
            os.remove(temp_path)
            
            # Show rejection reason
            issues = verification_result['issues']
            flash(f"Submission rejected: {'; '.join(issues)}", 'danger')
            
            if verification_result['recommendation'] == 'reject_duplicate':
                flash("You've already submitted this bug! Each bug can only be submitted once.", 'warning')
            
            return redirect(url_for('bugs_advanced.submit_bug_advanced'))
        
        # Step 5: Rename to permanent filename
        final_filename = f"{current_user.id}_{timestamp}_{filename}"
        final_path = os.path.join(current_app.config['UPLOAD_FOLDER'], final_filename)
        os.rename(temp_path, final_path)
        
        # Step 6: Extract vision data
        vision_result = verification_result.get('vision_result', {})
        species_info = verification_result.get('species_info')
        
        # Step 7: Create Bug entry
        bug = Bug(
            nickname=nickname,
            description=description,
            location_found=location_found,
            image_path=final_filename,
            user_id=current_user.id,
            
            # Vision verification data
            vision_verified=True,
            vision_confidence=vision_result.get('confidence', 0),
            vision_identified_species=vision_result.get('identified_species'),
            vision_quality_score=vision_result.get('quality_score', 0),
            
            # Generate image hash
            image_hash=str(imagehash.average_hash(Image.open(final_path))),
            
            # Link to species if identified
            species_id=species_info['species_id'] if species_info else None,
            common_name=species_info['common_name'] if species_info else None,
            scientific_name=species_info['scientific_name'] if species_info else vision_result.get('identified_species'),
            
            # Mark for review if confidence is borderline
            requires_manual_review=(vision_result.get('confidence', 1) < 0.85)
        )
        
        db.session.add(bug)
        db.session.flush()  # Get bug.id without committing
        
        # Step 8: Generate stats using LLM
        stat_generator = LLMStatGenerator()
        
        bug_info = {
            'scientific_name': bug.scientific_name,
            'common_name': bug.common_name,
            'size_mm': bug.species_info.average_size_mm if bug.species_info else None,
            'traits': _extract_traits_from_bug(bug),
            'species_info': bug.species_info.to_dict() if bug.species_info else None
        }
        
        stats = stat_generator.generate_stats_with_llm(bug_info)
        
        # Apply stats
        bug.attack = stats['attack']
        bug.defense = stats['defense']
        bug.speed = stats['speed']
        bug.special_ability = stats.get('special_ability')
        bug.stats_generation_method = 'llm_contextual'
        bug.stats_generated = True
        
        # Step 9: Assign tier
        tier_recommendation = assign_tier_and_generate_stats(bug)
        bug.tier = tier_recommendation['tier']
        
        # Step 10: Auto-generate flair
        bug.generate_flair()
        
        # Commit everything
        db.session.commit()
        
        # Step 11: Show success with warnings if any
        flash(f'{nickname} has entered the {tier_recommendation["tier_name"]} tier! {tier_recommendation["tier_icon"]}', 'success')
        
        if verification_result.get('warnings'):
            for warning in verification_result['warnings']:
                flash(f'Note: {warning}', 'info')
        
        if bug.requires_manual_review:
            flash('Your bug will be reviewed by moderators to confirm species identification.', 'info')
        
        return redirect(url_for('bugs.view_bug', bug_id=bug.id))
        
    except Exception as e:
        # Cleanup on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        db.session.rollback()
        flash(f'Error processing submission: {str(e)}', 'danger')
        return redirect(url_for('bugs_advanced.submit_bug_advanced'))


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


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


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
    return redirect(url_for('bugs_advanced.review_bugs'))


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
    return redirect(url_for('bugs_advanced.review_bugs'))