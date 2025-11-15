"""
User Permission System
Roles: Owner, Admin, Moderator, User

Owners can:
- Everything admins can do
- Assign/revoke admin status
- Change system-wide settings
- Delete tournaments

Admins can:
- View secret bug stats (xfactor, hidden lore)
- See matchup predictions with percentages
- Approve/reject bug submissions
- Moderate tournaments
- Assign moderator status

Moderators can:
- Review flagged bugs
- Approve bug submissions
- Create tournaments
- Moderate comments/lore

Users can:
- Submit bugs
- Enter tournaments
- Create battles
- Add lore/comments
"""

from enum import Enum
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user


class UserRole(Enum):
    """User permission levels"""
    OWNER = 4      # Full system access
    ADMIN = 3      # Can see secrets, manage users
    MODERATOR = 2  # Can moderate content
    USER = 1       # Standard access
    
    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented
    
    def __le__(self, other):
        if self.__class__ is other.__class__:
            return self.value <= other.value
        return NotImplemented
    
    def __gt__(self, other):
        if self.__class__ is other.__class__:
            return self.value > other.value
        return NotImplemented
    
    def __ge__(self, other):
        if self.__class__ is other.__class__:
            return self.value >= other.value
        return NotImplemented


def require_role(minimum_role: UserRole):
    """
    Decorator to require a minimum role for a route
    
    Usage:
        @bp.route('/admin/secrets')
        @require_role(UserRole.ADMIN)
        def view_secrets():
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('auth.login'))
            
            user_role = UserRole[current_user.role]
            
            if user_role < minimum_role:
                flash(f'You need {minimum_role.name} privileges to access this page.', 'danger')
                abort(403)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def is_owner(user):
    """Check if user is owner"""
    return user.is_authenticated and user.role == 'OWNER'


def is_admin(user):
    """Check if user is admin or owner"""
    if not user.is_authenticated:
        return False
    user_role = UserRole[user.role]
    return user_role >= UserRole.ADMIN


def is_moderator(user):
    """Check if user is moderator, admin, or owner"""
    if not user.is_authenticated:
        return False
    user_role = UserRole[user.role]
    return user_role >= UserRole.MODERATOR


def can_edit_bug(user, bug):
    """Check if user can edit a bug"""
    if not user.is_authenticated:
        return False
    # Users can edit their own bugs, mods+ can edit any
    return bug.user_id == user.id or is_moderator(user)


def can_view_secrets(user):
    """Check if user can view secret stats (xfactor, hidden lore)"""
    return is_admin(user)


# Admin-only views and services

class AdminBugAnalyzer:
    """Admin-only tools for viewing secret bug data"""
    
    @staticmethod
    def get_bug_secrets(bug) -> dict:
        """Get all secret data for a bug (admin only)"""
        from app.models import Bug
        
        return {
            'xfactor': {
                'value': bug.xfactor,
                'reason': bug.xfactor_reason,
                'impact': f"{bug.xfactor * 2:+.1f}% power modifier"
            },
            'visual_lore': {
                'items': bug.visual_lore_items,
                'environment': bug.visual_lore_environment,
                'posture': bug.visual_lore_posture,
                'analysis': bug.visual_lore_analysis,
                'unique_features': bug.visual_lore_unique_features
            },
            'stats_breakdown': {
                'attack': bug.attack,
                'defense': bug.defense,
                'speed': bug.speed,
                'total': bug.attack + bug.defense + bug.speed,
                'tier': bug.tier,
                'generation_method': bug.stats_generation_method
            }
        }
    
    @staticmethod
    def predict_battle_outcome(bug1, bug2) -> dict:
        """
        Predict battle outcome with percentage (admin only)
        
        Returns:
            {
                'bug1_win_chance': float (0-100),
                'bug2_win_chance': float (0-100),
                'expected_winner': Bug,
                'factors': list of advantage descriptions,
                'confidence': str ('high', 'medium', 'low')
            }
        """
        from app.services.battle_engine import determine_winner_with_xfactor
        
        # Calculate base power
        def calculate_power(bug):
            base = (
                bug.attack * 2.0 +
                bug.defense * 1.5 +
                bug.speed * 1.2
            )
            # Apply xfactor
            xfactor_mult = 1.0 + (bug.xfactor * 0.02)
            return base * xfactor_mult
        
        power1 = calculate_power(bug1)
        power2 = calculate_power(bug2)
        total_power = power1 + power2
        
        bug1_chance = (power1 / total_power) * 100 if total_power > 0 else 50
        bug2_chance = 100 - bug1_chance
        
        # Determine factors
        factors = []
        
        if bug1.xfactor > bug2.xfactor:
            factors.append(f"{bug1.nickname} has hidden advantage (+{bug1.xfactor:.1f} xfactor)")
        elif bug2.xfactor > bug1.xfactor:
            factors.append(f"{bug2.nickname} has hidden advantage (+{bug2.xfactor:.1f} xfactor)")
        
        if bug1.attack > bug2.attack + 2:
            factors.append(f"{bug1.nickname} has superior attack power")
        elif bug2.attack > bug1.attack + 2:
            factors.append(f"{bug2.nickname} has superior attack power")
        
        if bug1.speed > bug2.speed + 2:
            factors.append(f"{bug1.nickname} is much faster")
        elif bug2.speed > bug1.speed + 2:
            factors.append(f"{bug2.nickname} is much faster")
        
        if bug1.defense > bug2.defense + 2:
            factors.append(f"{bug1.nickname} has strong defenses")
        elif bug2.defense > bug1.defense + 2:
            factors.append(f"{bug2.nickname} has strong defenses")
        
        # Confidence based on difference
        diff = abs(bug1_chance - 50)
        if diff > 30:
            confidence = 'high'
        elif diff > 15:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        return {
            'bug1_win_chance': round(bug1_chance, 1),
            'bug2_win_chance': round(bug2_chance, 1),
            'expected_winner': bug1 if bug1_chance > 50 else bug2,
            'factors': factors,
            'confidence': confidence,
            'power_breakdown': {
                'bug1_power': round(power1, 2),
                'bug2_power': round(power2, 2)
            }
        }
    
    @staticmethod
    def get_tier_distribution() -> dict:
        """Get statistics on tier distribution (admin only)"""
        from app.models import Bug
        from app import db
        
        tier_counts = db.session.query(
            Bug.tier,
            db.func.count(Bug.id).label('count')
        ).group_by(Bug.tier).all()
        
        total = sum(count for _, count in tier_counts)
        
        return {
            tier: {
                'count': count,
                'percentage': round((count / total) * 100, 1) if total > 0 else 0
            }
            for tier, count in tier_counts
        }


class AdminUserManager:
    """Admin tools for managing users"""
    
    @staticmethod
    def assign_role(user, new_role: UserRole, assigned_by):
        """Assign a role to a user (requires appropriate permissions)"""
        if not is_owner(assigned_by) and new_role >= UserRole.ADMIN:
            raise PermissionError("Only owners can assign admin or owner roles")
        
        if not is_admin(assigned_by) and new_role >= UserRole.MODERATOR:
            raise PermissionError("Only admins can assign moderator roles")
        
        user.role = new_role.name
        
        from app import db
        db.session.commit()
        
        return True
    
    @staticmethod
    def get_user_stats(user) -> dict:
        """Get comprehensive user statistics"""
        from app.models import Bug, Battle, Comment, BugLore
        
        bugs_submitted = Bug.query.filter_by(user_id=user.id).count()
        total_wins = sum(bug.wins for bug in user.bugs.all())
        total_losses = sum(bug.losses for bug in user.bugs.all())
        
        comments_made = Comment.query.filter_by(user_id=user.id).count()
        lore_entries = BugLore.query.filter_by(user_id=user.id).count()
        
        return {
            'bugs_submitted': bugs_submitted,
            'total_wins': total_wins,
            'total_losses': total_losses,
            'win_rate': round((total_wins / (total_wins + total_losses)) * 100, 1) if (total_wins + total_losses) > 0 else 0,
            'comments_made': comments_made,
            'lore_entries': lore_entries,
            'account_age_days': (db.func.julianday('now') - db.func.julianday(user.created_at))
        }