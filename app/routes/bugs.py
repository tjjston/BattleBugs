from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import db
from app.models import Bug, Comment, BugLore
import os
from datetime import datetime

bp = Blueprint('bugs', __name__)

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route('/bugs')
def list_bugs():
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config['BUGS_PER_PAGE']
    bugs = Bug.query.order_by(Bug.submission_date.desc())\
        .paginate(page=page, per_page=current_app.config['BUGS_PER_PAGE'], error_out=False)
    return render_template('bugs/list.html', bugs=bugs)

@bp.route('/bugs/<int:bug_id>')
def view_bug(bug_id):
    bug = Bug.query.get_or_404(bug_id)
    comments = Comment.query.filter_by(bug_id=bug_id)\
        .order_by(Comment.created_at.desc()).all()
    lore = BugLore.query.filter_by(bug_id=bug_id)\
        .order_by(BugLore.upvotes.desc()).all()
    
    return render_template('bug_profile.html', bug=bug, comments=comments, lore=lore)

@bp.route('/bug/submit', methods=['GET', 'POST'])
@login_required
def submit_bug():
    if request.method == 'POST':
        name = request.form.get('name')
        species = request.form.get('species')
        description = request.form.get('description')

        if 'image' not in request.files:
            flash('No image provided', 'danger')
            return redirect(request.url)
        
        file = request.files['image']
        
        if file.filename == '':
            flash('No image selected', 'danger')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{current_user.id}_{timestamp}_{filename}"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            bug = Bug(
                name=name,
                species=species,
                description=description,
                image_path=filename,
                user_id=current_user.id
            )
            
            db.session.add(bug)
            db.session.commit()
            
            flash(f'{name} has entered the arena!', 'success')
            return redirect(url_for('bugs.view_bug', bug_id=bug.id))
        else:
            flash('Invalid file type. Please upload an image.', 'danger')
    
    return render_template('submit_bug.html')

@bp.route('/bug/<int:bug_id>/comment', methods=['POST'])
@login_required
def add_comment(bug_id):
    bug = Bug.query.get_or_404(bug_id)
    text = request.form.get('comment')
    
    if text:
        comment = Comment(text=text, bug_id=bug_id, user_id=current_user.id)
        db.session.add(comment)
        db.session.commit()
        flash('Comment added!', 'success')
    
    return redirect(url_for('bugs.view_bug', bug_id=bug_id))

@bp.route('/bug/<int:bug_id>/lore', methods=['POST'])
@login_required
def add_lore(bug_id):
    bug = Bug.query.get_or_404(bug_id)
    lore_text = request.form.get('lore')
    
    if lore_text:
        lore = BugLore(lore_text=lore_text, bug_id=bug_id, user_id=current_user.id)
        db.session.add(lore)
        db.session.commit()
        flash('Lore added to the archives!', 'success')
    
    return redirect(url_for('bugs.view_bug', bug_id=bug_id))