"""
Enhanced Bug Model with User Lore + Hidden Visual Lore System
This integrates with your existing models.py
"""

from datetime import datetime
from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(20), default='USER')  # USER, MODERATOR, ADMIN, OWNER
    elo = db.Column(db.Integer, default=1000)
    is_active = db.Column(db.Boolean, default=True)
    is_banned = db.Column(db.Boolean, default=False)
    warnings = db.Column(db.Integer, default=0)
    comments_made = db.Column(db.Integer, default=0)
    tournaments_participated = db.Column(db.Integer, default=0)
    tournaments_won = db.Column(db.Integer, default=0)
    bugs_submitted = db.Column(db.Integer, default=0)
    best_bug_elo = db.Column(db.Integer, default=0)

    
    # Relationships
    bugs = db.relationship('Bug', backref='owner', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    lore_entries = db.relationship('BugLore', backref='author', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class Species(db.Model):
    """Taxonomy database"""
    id = db.Column(db.Integer, primary_key=True)
    
    # Taxonomy
    scientific_name = db.Column(db.String(200), unique=True, nullable=False, index=True)
    common_name = db.Column(db.String(200))
    kingdom = db.Column(db.String(100), default='Animalia')
    phylum = db.Column(db.String(100), default='Arthropoda')
    class_name = db.Column(db.String(100), default='Insecta')
    order = db.Column(db.String(100))
    family = db.Column(db.String(100))
    genus = db.Column(db.String(100))
    species = db.Column(db.String(100))
    
    # Additional info
    description = db.Column(db.Text)
    habitat = db.Column(db.String(500))
    diet = db.Column(db.String(200))
    average_size_mm = db.Column(db.Float)
    average_weight_mg = db.Column(db.Float)
    
    # Combat characteristics
    has_venom = db.Column(db.Boolean, default=False)
    has_pincers = db.Column(db.Boolean, default=False)
    has_stinger = db.Column(db.Boolean, default=False)
    can_fly = db.Column(db.Boolean, default=False)
    has_armor = db.Column(db.Boolean, default=False)
    
    # External references
    gbif_id = db.Column(db.String(100))
    inaturalist_id = db.Column(db.String(100))
    wikipedia_url = db.Column(db.String(500))
    
    # Cache metadata
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    data_source = db.Column(db.String(100))
    
    # Relationships
    bugs = db.relationship('Bug', backref='species_info', lazy='dynamic')

    image_url = db.Column(db.String(500)) 
    
    def to_dict(self):
        return {
            'id': self.id,
            'scientific_name': self.scientific_name,
            'common_name': self.common_name,
            'order': self.order,
            'family': self.family,
            'characteristics': {
                'has_venom': self.has_venom,
                'has_pincers': self.has_pincers,
                'has_stinger': self.has_stinger,
                'can_fly': self.can_fly,
                'has_armor': self.has_armor
            }
        }


class Bug(db.Model):
    """Enhanced Bug model with user lore and hidden visual lore"""
    id = db.Column(db.Integer, primary_key=True)
    
    # Names (three-tier naming)
    nickname = db.Column(db.String(100), nullable=False)  # User's creative name
    common_name = db.Column(db.String(200))  # Common species name
    scientific_name = db.Column(db.String(200))  # Scientific name
    
    # For backwards compatibility with your templates
    @property
    def name(self):
        return self.nickname
    
    @property
    def species(self):
        return self.common_name or self.scientific_name
    
    # Taxonomy reference
    species_id = db.Column(db.Integer, db.ForeignKey('species.id'))
    
    # Visual
    image_path = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)  # User's description/story
    
    # USER-INPUT LORE FIELDS (Public - shown in UI)

    lore_interests = db.Column(db.Text)  # What does this bug like?
    lore_background = db.Column(db.Text)  # Where did it come from?
    lore_motivation = db.Column(db.Text)  # Why does it fight?
    lore_religion = db.Column(db.String(200))  # Spiritual beliefs
    lore_personality = db.Column(db.Text)  # Personality traits
    lore_fears = db.Column(db.Text)  # What does it fear?
    lore_allies = db.Column(db.Text)  # Friends/allies
    lore_rivals = db.Column(db.Text)  # Enemies/rivals
    
    # LLM Lore

    visual_lore_analysis = db.Column(db.Text)  # LLM observations
    visual_lore_items = db.Column(db.Text)  # Items/weapons found in photo
    visual_lore_environment = db.Column(db.Text)  # Environmental advantages
    visual_lore_posture = db.Column(db.Text)  # Battle stance/readiness
    visual_lore_unique_features = db.Column(db.Text)  # Special visual traits

    # STATS (visible + hidden xfactor)

    attack = db.Column(db.Integer, default=5)
    defense = db.Column(db.Integer, default=5)
    speed = db.Column(db.Integer, default=5)
    special_attack = db.Column(db.Integer, default=5)
    special_defense = db.Column(db.Integer, default=5)
    health = db.Column(db.Integer, default=100)
    # Combat characteristic fields (visible + used in battle logic)
    attack_type = db.Column(db.String(50))   # e.g., piercing, crushing, slashing, venom, chemical, grappling
    defense_type = db.Column(db.String(50))  # e.g., hard_shell, segmented_armor, evasive, hairy_spiny, toxic_skin, thick_hide
    size_class = db.Column(db.String(20))    # tiny, small, medium, large, massive
    
    xfactor = db.Column(db.Float, default=0.0)  # -5.0 to +5.0 hidden modifier
    xfactor_reason = db.Column(db.Text)
    
    special_ability = db.Column(db.String(200))
    
    # Stats metadata
    stats_generated = db.Column(db.Boolean, default=False)
    stats_generation_method = db.Column(db.String(50))
    
    # Flair system
    flair = db.Column(db.String(100))
    title = db.Column(db.String(100))
    
    # Tier system (for tournaments)
    tier = db.Column(db.String(20))  # 'uber', 'ou', 'uu', 'ru', 'nu', 'zu'
    
    # Vision verification
    vision_verified = db.Column(db.Boolean, default=False)
    vision_confidence = db.Column(db.Float)
    vision_identified_species = db.Column(db.String(200))
    vision_quality_score = db.Column(db.Float)
    image_hash = db.Column(db.String(64)) 
    requires_manual_review = db.Column(db.Boolean, default=False)
    review_notes = db.Column(db.Text)
    
    # Location data
    location_found = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    found_date = db.Column(db.DateTime)
    
    # Metadata
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    submission_date = db.Column(db.DateTime, default=datetime.utcnow)
    wins = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    is_verified = db.Column(db.Boolean, default=False)
    
    # Relationships
    comments = db.relationship('Comment', backref='bug', lazy='dynamic', cascade='all, delete-orphan')
    lore = db.relationship('BugLore', backref='bug', lazy='dynamic', cascade='all, delete-orphan')
    battles_as_bug1 = db.relationship('Battle', foreign_keys='Battle.bug1_id', backref='bug1', lazy='dynamic')
    battles_as_bug2 = db.relationship('Battle', foreign_keys='Battle.bug2_id', backref='bug2', lazy='dynamic')
    achievements = db.relationship('BugAchievement', backref='bug', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Bug {self.nickname}>'
    
    @property
    def win_rate(self):
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0
    
    @property
    def display_name(self):
        """Get the best display name available"""
        return self.nickname or self.common_name or self.scientific_name or "Unknown Bug"
    
    @property
    def full_taxonomy(self):
        """Get full taxonomy string"""
        if self.species_info:
            parts = [
                self.species_info.order,
                self.species_info.family,
                self.species_info.genus,
                self.species_info.species
            ]
            return ' → '.join(filter(None, parts))
        return None
    
    def generate_flair(self):
        """Auto-generate flair based on performance"""
        if self.wins >= 10:
            self.flair = "🏆 Arena Legend"
        elif self.win_rate >= 80 and self.wins >= 5:
            self.flair = "⚡ Dominator"
        elif self.wins >= 5:
            self.flair = "⚔️ Veteran"
        elif self.speed >= 8:
            self.flair = "💨 Speedster"
        elif self.defense >= 8:
            self.flair = "🛡️ Tank"
        elif self.attack >= 8:
            self.flair = "🔥 Powerhouse"
        else:
            self.flair = "🌟 Rising Star"
        
        db.session.commit()
        return self.flair
    
    def get_public_lore(self):
        """Get all user-input lore fields as dictionary"""
        return {
            'interests': self.lore_interests,
            'background': self.lore_background,
            'motivation': self.lore_motivation,
            'religion': self.lore_religion,
            'personality': self.lore_personality,
            'fears': self.lore_fears,
            'allies': self.lore_allies,
            'rivals': self.lore_rivals,
            'combat': {
                'attack_type': self.attack_type,
                'defense_type': self.defense_type,
                'size_class': self.size_class
            }
        }
    
    def get_secret_lore(self):
        """Get hidden visual lore (only for LLM, never shown to users)"""
        return {
            'visual_analysis': self.visual_lore_analysis,
            'items_weapons': self.visual_lore_items,
            'environment': self.visual_lore_environment,
            'posture': self.visual_lore_posture,
            'unique_features': self.visual_lore_unique_features,
            'xfactor': self.xfactor,
            'xfactor_reason': self.xfactor_reason
        }


class BugAchievement(db.Model):
    """Achievement/badge system for bugs"""
    id = db.Column(db.Integer, primary_key=True)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    achievement_type = db.Column(db.String(50), nullable=False)
    achievement_name = db.Column(db.String(100), nullable=False)
    achievement_icon = db.Column(db.String(10))
    description = db.Column(db.Text)
    earned_date = db.Column(db.DateTime, default=datetime.utcnow)
    rarity = db.Column(db.String(20))
    
    def __repr__(self):
        return f'<Achievement {self.achievement_name}>'


class Battle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bug1_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    bug2_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    winner_id = db.Column(db.Integer, db.ForeignKey('bug.id'))
    winner = db.relationship('Bug', foreign_keys=[winner_id])
    
    narrative = db.Column(db.Text)
    battle_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Tournament relationship
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'))
    round_number = db.Column(db.Integer)
    
    # Store which bug had xfactor advantage (for post-battle reveal)
    xfactor_triggered = db.Column(db.Boolean, default=False)
    xfactor_details = db.Column(db.Text)  # What secret advantage was used?
    
    def __repr__(self):
        return f'<Battle {self.id}: Bug{self.bug1_id} vs Bug{self.bug2_id}>'


class Tournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime)
    winner_id = db.Column(db.Integer, db.ForeignKey('bug.id'))
    status = db.Column(db.String(20), default='upcoming')
    max_participants = db.Column(db.Integer)
    
    # Tier restriction
    tier = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    registration_deadline = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    allow_tier_above = db.Column(db.Boolean, default=False)
    
    battles = db.relationship('Battle', backref='tournament', lazy='dynamic')
    winner = db.relationship('Bug', foreign_keys=[winner_id])
    
    def __repr__(self):
        return f'<Tournament {self.name}>'
    
    @property
    def tier_restriction(self):
        """Compatibility alias: some services use `tier_restriction` name."""
        return self.tier

    @tier_restriction.setter
    def tier_restriction(self, value):
        self.tier = value
    
class TournamentApplication(db.Model):
    """Model for tournament applications"""
    __tablename__ = 'tournament_applications'
    
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected, withdrawn
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Seeding (for bracket generation)
    seed_number = db.Column(db.Integer)  # 1-N ranking for bracket placement
    
    # Relationships
    tournament = db.relationship('Tournament', backref='applications')
    bug = db.relationship('Bug', backref='tournament_applications')
    user = db.relationship('User', foreign_keys=[user_id], backref='tournament_applications')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id])
    
    def __repr__(self):
        return f'<TournamentApplication {self.bug.nickname} -> {self.tournament.name}>'

class TournamentMatch(db.Model):
    """Model for individual tournament matches (extends Battle)"""
    __tablename__ = 'tournament_matches'
    
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    battle_id = db.Column(db.Integer, db.ForeignKey('battle.id'))
    
    round_number = db.Column(db.Integer, nullable=False)  # 1, 2, 3, etc.
    match_number = db.Column(db.Integer, nullable=False)  # Position in round
    
    bug1_id = db.Column(db.Integer, db.ForeignKey('bug.id'))
    bug2_id = db.Column(db.Integer, db.ForeignKey('bug.id'))
    winner_id = db.Column(db.Integer, db.ForeignKey('bug.id'))
    
    # For tracking progression
    next_match_id = db.Column(db.Integer, db.ForeignKey('tournament_matches.id'))
    
    scheduled_for = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    
    # Relationships
    tournament = db.relationship('Tournament', backref='matches')
    battle = db.relationship('Battle')
    bug1 = db.relationship('Bug', foreign_keys=[bug1_id])
    bug2 = db.relationship('Bug', foreign_keys=[bug2_id])
    winner = db.relationship('Bug', foreign_keys=[winner_id])
    next_match = db.relationship('TournamentMatch', remote_side=[id], backref='previous_matches')

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    upvotes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Comment {self.id}>'


class BugLore(db.Model):
    """Community-created lore entries"""
    id = db.Column(db.Integer, primary_key=True)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lore_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    upvotes = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f'<BugLore {self.id}>'