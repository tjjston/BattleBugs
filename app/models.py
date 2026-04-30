"""
Enhanced Bug Model with User Lore + Hidden Visual Lore System
This integrates with your existing models.py
"""

from datetime import datetime, timezone
import json

def _now():
    return datetime.now(timezone.utc)
from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=_now)
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
    accolade_points = db.Column(db.Integer, default=0)

    # Species-guess accuracy tracking (cosmetic badges only)
    total_guesses   = db.Column(db.Integer, default=0)
    correct_guesses = db.Column(db.Integer, default=0)
    skipped_guesses = db.Column(db.Integer, default=0)

    # Relationships
    bugs = db.relationship('Bug', backref='owner', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    lore_entries = db.relationship('BugLore', backref='author', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def guess_badge(self):
        """Return cosmetic badge dict based on species-guess accuracy, or None."""
        total   = self.total_guesses   or 0
        correct = self.correct_guesses or 0
        skipped = self.skipped_guesses or 0

        # Never bothered guessing with meaningful submission history
        if total == 0:
            if skipped >= 5:
                return {'icon': '🦆', 'name': 'Above It All', 'color': 'secondary',
                        'desc': "Has never attempted a species identification"}
            return None

        # Only one guess ever, and it was correct
        if total == 1 and correct == 1:
            return {'icon': '🍀', 'name': "Beginner's Luck", 'color': 'success',
                    'desc': "Nailed it on the first and only try"}

        # Need at least 5 guesses before an accuracy badge is awarded
        if total < 5:
            return None

        accuracy = correct / total
        if accuracy >= 0.90:
            return {'icon': '🏆', 'name': 'Perfect Identifier', 'color': 'warning',
                    'desc': 'Near-flawless species identification accuracy'}
        if accuracy >= 0.70:
            return {'icon': '🔬', 'name': 'Expert Entomologist', 'color': 'primary',
                    'desc': 'Consistently accurate — knows their bugs cold'}
        if accuracy >= 0.50:
            return {'icon': '🦋', 'name': 'Bug Whisperer', 'color': 'info',
                    'desc': 'More often right than wrong'}
        if accuracy >= 0.30:
            return {'icon': '🎯', 'name': 'Field Researcher', 'color': 'secondary',
                    'desc': 'Trying their best out there'}
        if accuracy >= 0.10:
            return {'icon': '🎰', 'name': 'Shot in the Dark', 'color': 'warning',
                    'desc': 'Guesses with wild optimism, occasionally gets lucky'}
        return {'icon': '🤡', 'name': 'Spectacularly Wrong', 'color': 'danger',
                'desc': 'Confidently incorrect, every single time'}

    @property
    def earned_badges(self):
        """Compute accolade badges from existing stats — no DB queries."""
        badges = []
        won = self.tournaments_won or 0
        if won >= 5:
            badges.append({'icon': '👑', 'name': 'Grand Marshal', 'color': 'warning text-dark', 'desc': '5+ tournament wins'})
        elif won >= 3:
            badges.append({'icon': '🏆', 'name': 'Champion Dynasty', 'color': 'warning text-dark', 'desc': '3+ tournament wins'})
        elif won >= 1:
            badges.append({'icon': '🥇', 'name': 'Tournament Champion', 'color': 'warning text-dark', 'desc': 'Won a tournament'})

        sub = self.bugs_submitted or 0
        if sub >= 30:
            badges.append({'icon': '🏛️', 'name': 'Field Marshal', 'color': 'primary', 'desc': '30+ bugs submitted'})
        elif sub >= 15:
            badges.append({'icon': '🔬', 'name': 'Entomologist', 'color': 'primary', 'desc': '15+ bugs submitted'})
        elif sub >= 5:
            badges.append({'icon': '🕵️', 'name': 'Bug Wrangler', 'color': 'info text-dark', 'desc': '5+ bugs submitted'})
        elif sub >= 1:
            badges.append({'icon': '🐛', 'name': 'Bug Catcher', 'color': 'success', 'desc': 'First bug submitted'})

        elo = self.elo or 1000
        if elo >= 1500:
            badges.append({'icon': '⚡', 'name': 'Apex Predator', 'color': 'danger', 'desc': 'ELO 1500+'})
        elif elo >= 1300:
            badges.append({'icon': '🌟', 'name': 'Arena Legend', 'color': 'warning text-dark', 'desc': 'ELO 1300+'})
        elif elo >= 1100:
            badges.append({'icon': '🎯', 'name': 'Arena Veteran', 'color': 'secondary', 'desc': 'ELO 1100+'})

        ap = self.accolade_points or 0
        if ap >= 500:
            badges.append({'icon': '💎', 'name': 'Patron', 'color': 'info text-dark', 'desc': '500+ AP'})
        elif ap >= 100:
            badges.append({'icon': '💰', 'name': 'Contributor', 'color': 'secondary', 'desc': '100+ AP'})

        return badges

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
    gbif_backbone_key = db.Column(db.Integer)          # GBIF backbone usageKey (canonical)
    accepted_name = db.Column(db.String(200))           # Canonical accepted name if this was a synonym
    inaturalist_id = db.Column(db.String(100))
    catalogue_of_life_id = db.Column(db.String(100))   # COL ChecklistBank ID
    wikipedia_url = db.Column(db.String(500))
    interesting_facts = db.Column(db.Text)  # JSON-encoded list[str] from Wikipedia/iNaturalist
    conservation_status = db.Column(db.String(50))      # IUCN: LC, NT, VU, EN, CR, EW, EX
    observation_count = db.Column(db.Integer)           # iNaturalist research-grade observations

    # Cache metadata
    last_updated = db.Column(db.DateTime, default=_now)
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
    # Legacy columns kept for DB compat; no longer used in battle formula
    special_attack = db.Column(db.Integer, default=5)
    special_defense = db.Column(db.Integer, default=5)
    health = db.Column(db.Integer, default=100)
    # Extended combat stats (replace the legacy three above in the formula)
    lethality = db.Column(db.Integer, default=50)   # weapon/venom potency; amplifies type advantage
    grip = db.Column(db.Integer, default=50)        # engagement control; counters speed/evasion
    cunning = db.Column(db.Integer, default=50)     # tactical instinct; partially offsets type disadvantage
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
    enrichment_status = db.Column(db.String(20), default='pending')  # pending, processing, complete, failed
    enrichment_error = db.Column(db.Text)
    
    # Location data
    location_found = db.Column(db.String(200))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    found_date = db.Column(db.DateTime)
    
    # Metadata
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    submission_date = db.Column(db.DateTime, default=_now, index=True)
    wins = db.Column(db.Integer, default=0)
    losses = db.Column(db.Integer, default=0)
    is_verified = db.Column(db.Boolean, default=False)

    # Retirement
    is_retired = db.Column(db.Boolean, default=False)
    retired_at = db.Column(db.DateTime)

    # Competition track: 'season' | 'mma' | None (unassigned)
    bug_track = db.Column(db.String(20), nullable=True)

    # Cumulative stat growth from battle milestones (display only)
    stat_growth = db.Column(db.Integer, default=0)

    # Physical condition detected at submission
    is_zombug = db.Column(db.Boolean, default=False)
    condition = db.Column(db.String(30), default='alive')    # alive|dead|squashed|damaged_wings|damaged_legs|damaged
    condition_notes = db.Column(db.Text)                     # LLM-observed description of the bug's state
    
    # Relationships
    comments = db.relationship('Comment', backref='bug', lazy='dynamic', cascade='all, delete-orphan')
    lore = db.relationship('BugLore', backref='bug', lazy='dynamic', cascade='all, delete-orphan')
    battles_as_bug1 = db.relationship('Battle', foreign_keys='Battle.bug1_id', backref='bug1', lazy='dynamic')
    battles_as_bug2 = db.relationship('Battle', foreign_keys='Battle.bug2_id', backref='bug2', lazy='dynamic')
    achievements = db.relationship('BugAchievement', backref='bug', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Bug {self.nickname}>'

    @property
    def combat_badges(self):
        """Computed display badges — no DB queries."""
        badges = []
        tier_colors = {'uber': 'danger', 'ou': 'warning text-dark', 'uu': 'primary',
                       'ru': 'info text-dark', 'nu': 'secondary', 'zu': 'dark'}
        if self.tier:
            badges.append({'icon': '🏅', 'name': self.tier.upper(),
                           'color': tier_colors.get(self.tier, 'secondary'), 'type': 'tier'})

        atk_map = {
            'piercing':  ('⚔️',  'Piercer',   'danger'),
            'crushing':  ('💥',  'Crusher',   'warning text-dark'),
            'slashing':  ('🔪',  'Slasher',   'danger'),
            'venom':     ('☠️',  'Venomous',  'success'),
            'chemical':  ('⚗️',  'Chemical',  'info text-dark'),
            'grappling': ('🤼',  'Grappler',  'primary'),
            'sonic':     ('🔊',  'Sonar',     'primary'),
            'electric':  ('⚡',  'Electric',  'warning text-dark'),
            'neutral':   ('⚪',  'Balanced',  'secondary'),
        }
        def_map = {
            'hard_shell':      ('🛡️',  'Armored',      'secondary'),
            'segmented_armor': ('🔗',  'Segmented',    'secondary'),
            'evasive':         ('💨',  'Elusive',      'info text-dark'),
            'hairy_spiny':     ('🦔',  'Spiny',        'warning text-dark'),
            'toxic_skin':      ('☢️',  'Toxic',        'success'),
            'thick_hide':      ('🦏',  'Thick Hide',   'dark'),
            'unarmored':       ('🫀',  'Resilient',    'danger'),
            'regenerative':    ('💚',  'Regenerative', 'success'),
            'bioluminescent':  ('✨',  'Bioluminescent','info text-dark'),
        }
        if self.attack_type in atk_map:
            icon, name, color = atk_map[self.attack_type]
            badges.append({'icon': icon, 'name': name, 'color': color, 'type': 'attack'})
        if self.defense_type in def_map:
            icon, name, color = def_map[self.defense_type]
            badges.append({'icon': icon, 'name': name, 'color': color, 'type': 'defense'})

        if (self.attack or 0) >= 8:
            badges.append({'icon': '🗡️', 'name': 'Berserker',  'color': 'danger',          'type': 'stat'})
        if (self.defense or 0) >= 8:
            badges.append({'icon': '🏰', 'name': 'Fortress',   'color': 'primary',         'type': 'stat'})
        if (self.speed or 0) >= 8:
            badges.append({'icon': '⚡', 'name': 'Lightning',  'color': 'warning text-dark','type': 'stat'})
        if (self.lethality or 0) >= 75:
            badges.append({'icon': '💀', 'name': 'Lethal',     'color': 'dark',            'type': 'stat'})
        if (self.grip or 0) >= 75:
            badges.append({'icon': '🦀', 'name': 'Vice Grip',  'color': 'secondary',       'type': 'stat'})
        if (self.cunning or 0) >= 75:
            badges.append({'icon': '🧠', 'name': 'Mastermind', 'color': 'info text-dark',  'type': 'stat'})

        wins = self.wins or 0
        if wins >= 50:
            badges.append({'icon': '🏆', 'name': '50W Legend',   'color': 'warning text-dark', 'type': 'milestone'})
        elif wins >= 20:
            badges.append({'icon': '🥇', 'name': '20W Champion', 'color': 'warning text-dark', 'type': 'milestone'})
        elif wins >= 10:
            badges.append({'icon': '🥈', 'name': '10W Veteran',  'color': 'secondary',         'type': 'milestone'})
        elif wins >= 5:
            badges.append({'icon': '🥉', 'name': '5W Fighter',   'color': 'secondary',         'type': 'milestone'})

        # Consolation badges for the bottom tiers — lovingly roasted
        if self.tier == 'zu':
            _zu = [
                ('🫧', 'Certified Harmless',  'secondary', 'zu_funny'),
                ('🪑', 'Permanent Bench',     'secondary', 'zu_funny'),
                ('🏳️', 'Participation Award', 'secondary', 'zu_funny'),
                ('🎖️', 'Tried Its Best',      'secondary', 'zu_funny'),
                ('💤', 'Deeply Misunderstood','secondary', 'zu_funny'),
                ('🛒', 'Gently Used',         'secondary', 'zu_funny'),
                ('🌈', 'Moral Victory',       'secondary', 'zu_funny'),
            ]
            b = _zu[(self.id or 0) % len(_zu)]
            badges.append({'icon': b[0], 'name': b[1], 'color': b[2], 'type': b[3]})
        elif self.tier == 'nu':
            _nu = [
                ('📋', 'Filed Away',          'dark', 'nu_funny'),
                ('🌱', 'Just Needs a Chance', 'success', 'nu_funny'),
                ('👻', 'Who?',                'secondary', 'nu_funny'),
                ('📦', 'Unopened Potential',  'secondary', 'nu_funny'),
                ('🎯', 'Niche Pick',          'info text-dark', 'nu_funny'),
                ('🔍', 'Statistically Present','secondary', 'nu_funny'),
            ]
            b = _nu[(self.id or 0) % len(_nu)]
            badges.append({'icon': b[0], 'name': b[1], 'color': b[2], 'type': b[3]})

        return badges

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
    earned_date = db.Column(db.DateTime, default=_now)
    rarity = db.Column(db.String(20))
    
    def __repr__(self):
        return f'<Achievement {self.achievement_name}>'


class Job(db.Model):
    """Lightweight background job record for enrichment and maintenance work."""
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(80), nullable=False, index=True)
    status = db.Column(db.String(20), default='queued', nullable=False, index=True)
    payload_json = db.Column(db.Text)
    result_json = db.Column(db.Text)
    error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    attempts = db.Column(db.Integer, default=0, nullable=False)

    @property
    def payload(self):
        if not self.payload_json:
            return {}
        try:
            return json.loads(self.payload_json)
        except (TypeError, ValueError):
            return {}

    @payload.setter
    def payload(self, value):
        self.payload_json = json.dumps(value or {})

    @property
    def result(self):
        if not self.result_json:
            return {}
        try:
            return json.loads(self.result_json)
        except (TypeError, ValueError):
            return {}

    @result.setter
    def result(self, value):
        self.result_json = json.dumps(value or {})

    def __repr__(self):
        return f'<Job {self.id} {self.type} {self.status}>'


class CurrencyTransaction(db.Model):
    """Ledger for player-earned and spent Accolade Points."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(120), nullable=False)
    reference_type = db.Column(db.String(50))
    reference_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=_now, nullable=False)

    user = db.relationship('User', backref=db.backref('currency_transactions', lazy='dynamic'))

    def __repr__(self):
        return f'<CurrencyTransaction {self.user_id} {self.amount} {self.reason}>'


class Battle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bug1_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    bug2_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    winner_id = db.Column(db.Integer, db.ForeignKey('bug.id'))
    winner = db.relationship('Bug', foreign_keys=[winner_id])
    
    narrative = db.Column(db.Text)
    battle_date = db.Column(db.DateTime, default=_now, index=True)
    
    # Tournament relationship
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'))
    round_number = db.Column(db.Integer)
    
    # Store which bug had xfactor advantage (for post-battle reveal)
    xfactor_triggered = db.Column(db.Boolean, default=False)
    xfactor_details = db.Column(db.Text)  # What secret advantage was used?

    # Battle venue and result flavour
    venue = db.Column(db.String(100))          # e.g. "The Flower Bed"
    battle_rating = db.Column(db.String(30))   # dominant|contested|nail_biter|upset

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
    created_at = db.Column(db.DateTime, default=_now)
    registration_deadline = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    season_key = db.Column(db.String(20))  # e.g. "spring_2026"; None for manual tournaments
    allow_tier_above = db.Column(db.Boolean, default=False)
    format = db.Column(db.String(30), default='single_elimination')  # single_elimination|double_elimination|swiss|round_robin
    submissions_per_user = db.Column(db.Integer, default=2)
    retirement_event = db.Column(db.Boolean, default=False)  # True = only retired bugs may enter
    
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
    applied_at = db.Column(db.DateTime, default=_now)
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
    created_at = db.Column(db.DateTime, default=_now)
    
    def __repr__(self):
        return f'<Comment {self.id}>'


class BugLore(db.Model):
    """Community-created lore entries"""
    id = db.Column(db.Integer, primary_key=True)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lore_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=_now)
    upvotes = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f'<BugLore {self.id}>'


class CommentVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_now)

    __table_args__ = (
        db.UniqueConstraint('comment_id', 'user_id', name='uq_comment_vote_user'),
    )


class BugLoreVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lore_id = db.Column(db.Integer, db.ForeignKey('bug_lore.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=_now)

    __table_args__ = (
        db.UniqueConstraint('lore_id', 'user_id', name='uq_lore_vote_user'),
    )


class BugRival(db.Model):
    """Tracks recurring opponents. Bug IDs are always stored with the lower ID first."""
    id = db.Column(db.Integer, primary_key=True)
    bug1_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    bug2_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    encounter_count = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=_now)
    last_encounter_at = db.Column(db.DateTime, default=_now)

    bug1_wins = db.Column(db.Integer, default=0, nullable=False)
    bug2_wins = db.Column(db.Integer, default=0, nullable=False)

    bug1 = db.relationship('Bug', foreign_keys=[bug1_id])
    bug2 = db.relationship('Bug', foreign_keys=[bug2_id])

    __table_args__ = (
        db.UniqueConstraint('bug1_id', 'bug2_id', name='uq_rival_pair'),
    )

    def other(self, bug_id: int):
        return self.bug2 if self.bug1_id == bug_id else self.bug1

    def __repr__(self):
        return f'<BugRival {self.bug1_id} vs {self.bug2_id} x{self.encounter_count}>'


class ClassificationFlag(db.Model):
    """User-submitted dispute of a bug's AI classification."""
    __tablename__ = 'classification_flag'

    id = db.Column(db.Integer, primary_key=True)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    flagging_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    suggested_species = db.Column(db.String(200))
    status = db.Column(db.String(20), default='pending', nullable=False)  # pending | reviewed | dismissed
    created_at = db.Column(db.DateTime, default=_now)
    reviewed_at = db.Column(db.DateTime)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    reviewer_notes = db.Column(db.Text)

    bug = db.relationship('Bug', backref=db.backref('classification_flags', lazy='dynamic'))
    flagging_user = db.relationship('User', foreign_keys=[flagging_user_id], backref='submitted_flags')
    reviewer = db.relationship('User', foreign_keys=[reviewer_id])

    __table_args__ = (
        db.UniqueConstraint('bug_id', 'flagging_user_id', name='uq_flag_per_user_per_bug'),
    )

    def __repr__(self):
        return f'<ClassificationFlag bug={self.bug_id} status={self.status}>'


class Notification(db.Model):
    """In-app notification for a user."""
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link_url = db.Column(db.String(500))
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    notification_type = db.Column(db.String(30), default='info')  # info|tournament_victory|season_result
    created_at = db.Column(db.DateTime, default=_now)

    user = db.relationship('User', backref=db.backref('notifications', lazy='dynamic'))

    def __repr__(self):
        return f'<Notification user={self.user_id} type={self.notification_type} read={self.is_read}>'


class Season(db.Model):
    """A competitive season: registration → regular season (daily matches) → playoff tournament."""
    __tablename__ = 'season'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    tier = db.Column(db.String(10), nullable=False)
    season_key = db.Column(db.String(40), unique=True, nullable=False)  # e.g. spring_2026_ou
    phase = db.Column(db.String(20), default='registration', nullable=False)
    # phases: registration → regular_season → tournament → completed

    registration_opens = db.Column(db.DateTime, nullable=False)
    registration_closes = db.Column(db.DateTime, nullable=False)
    regular_season_start = db.Column(db.DateTime, nullable=False)
    regular_season_end = db.Column(db.DateTime, nullable=False)
    tournament_start = db.Column(db.DateTime)
    tournament_end = db.Column(db.DateTime)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=True)
    max_registrations = db.Column(db.Integer, default=64)
    created_at = db.Column(db.DateTime, default=_now)

    registrations = db.relationship('SeasonRegistration', backref='season', lazy='dynamic',
                                    cascade='all, delete-orphan')
    matches = db.relationship('SeasonMatch', backref='season', lazy='dynamic',
                              cascade='all, delete-orphan')
    playoff = db.relationship('Tournament', foreign_keys=[tournament_id])

    def __repr__(self):
        return f'<Season {self.season_key} phase={self.phase}>'


class SeasonRegistration(db.Model):
    """A bug registered for a season, tracking boost points and auto-assign preference."""
    __tablename__ = 'season_registration'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    registered_at = db.Column(db.DateTime, default=_now)
    status = db.Column(db.String(20), default='registered')  # registered|active|eliminated
    pending_boost_points = db.Column(db.Integer, default=0)
    # null = manual; one of: attack|defense|speed|lethality|grip|cunning
    boost_auto_stat = db.Column(db.String(20))
    season_wins = db.Column(db.Integer, default=0)
    season_losses = db.Column(db.Integer, default=0)

    __table_args__ = (db.UniqueConstraint('season_id', 'bug_id', name='uq_season_bug'),)

    bug = db.relationship('Bug', backref=db.backref('season_registrations', lazy='dynamic'))
    user = db.relationship('User')

    def apply_pending_boost(self, stat: str) -> int:
        """Apply pending boost points to a stat on the bug. Returns points applied."""
        pts = self.pending_boost_points
        if pts <= 0 or stat not in ('attack', 'defense', 'speed', 'lethality', 'grip', 'cunning'):
            return 0
        current = getattr(self.bug, stat) or 0
        setattr(self.bug, stat, min(100, current + pts))
        self.pending_boost_points = 0
        return pts

    def __repr__(self):
        return f'<SeasonRegistration season={self.season_id} bug={self.bug_id}>'


class SeasonMatch(db.Model):
    """A scheduled regular-season match between two registered bugs."""
    __tablename__ = 'season_match'

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=False)
    bug1_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    bug2_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    battle_id = db.Column(db.Integer, db.ForeignKey('battle.id'), nullable=True)
    scheduled_at = db.Column(db.DateTime, nullable=False)
    completed_at = db.Column(db.DateTime)
    day_number = db.Column(db.Integer, nullable=False)  # 1-N
    match_type = db.Column(db.String(20), default='regular')  # 'regular' or 'tournament'

    bug1 = db.relationship('Bug', foreign_keys=[bug1_id])
    bug2 = db.relationship('Bug', foreign_keys=[bug2_id])
    battle = db.relationship('Battle')

    def __repr__(self):
        return f'<SeasonMatch season={self.season_id} day={self.day_number} bugs={self.bug1_id}v{self.bug2_id}>'


class BlockedImageHash(db.Model):
    """Image hashes permanently blocked from resubmission (e.g. failed zombug conversions)."""
    __tablename__ = 'blocked_image_hash'

    id = db.Column(db.Integer, primary_key=True)
    image_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    reason = db.Column(db.String(100), default='zombug_failed')
    created_at = db.Column(db.DateTime, default=_now)

    def __repr__(self):
        return f'<BlockedImageHash {self.image_hash[:8]}… reason={self.reason}>'


class SystemSetting(db.Model):
    """Admin-controlled key/value settings that override config defaults at runtime."""
    __tablename__ = 'system_setting'

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=_now)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    @classmethod
    def get(cls, key, default=None):
        """Return setting value or default. Safe to call outside app context."""
        try:
            row = db.session.get(cls, key)
            return row.value if row else default
        except Exception:
            return default

    @classmethod
    def set(cls, key, value, user_id=None):
        row = db.session.get(cls, key)
        if row:
            row.value = str(value)
            row.updated_at = datetime.now(timezone.utc)
            if user_id:
                row.updated_by_id = user_id
        else:
            row = cls(key=key, value=str(value), updated_by_id=user_id)
            db.session.add(row)

    def __repr__(self):
        return f'<SystemSetting {self.key}={self.value!r}>'


class RejectedSubmission(db.Model):
    """Stores failed bug submissions that the user sent for admin review."""
    __tablename__ = 'rejected_submission'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    image_path = db.Column(db.String(255))          # saved review-folder filename
    nickname = db.Column(db.String(100))
    description = db.Column(db.Text)
    location_found = db.Column(db.String(200))
    user_species_guess = db.Column(db.String(200))
    rejection_reasons = db.Column(db.Text)          # JSON list
    submitted_at = db.Column(db.DateTime, default=_now)
    status = db.Column(db.String(20), default='pending')  # pending / approved / dismissed
    admin_notes = db.Column(db.Text)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    submitter = db.relationship('User', foreign_keys=[user_id], backref='rejected_submissions')
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id])

    @property
    def reasons_list(self):
        try:
            return json.loads(self.rejection_reasons or '[]')
        except Exception:
            return []


# ── Championship / MMA Track ──────────────────────────────────────────────────

CHAMPIONSHIP_TIERS = ['uber', 'ou', 'uu', 'ru', 'nu', 'zu']

# Minimum AP bid required to challenge as each contender rank
CONTENDER_MIN_BIDS = {1: 0, 2: 50, 3: 150}


class TierChampionship(db.Model):
    """One record per tier tracking the current belt holder."""
    __tablename__ = 'tier_championship'

    id = db.Column(db.Integer, primary_key=True)
    tier = db.Column(db.String(20), nullable=False, unique=True)
    champion_bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=True)
    won_date = db.Column(db.DateTime, nullable=True)
    defense_count = db.Column(db.Integer, default=0)
    next_defense_due = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='vacant')  # active | vacant

    champion = db.relationship('Bug', foreign_keys=[champion_bug_id],
                               backref=db.backref('championship_held', uselist=False))


class TierRanking(db.Model):
    """Contender ranking entry — one per bug per tier."""
    __tablename__ = 'tier_ranking'

    id = db.Column(db.Integer, primary_key=True)
    tier = db.Column(db.String(20), nullable=False, index=True)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    rank = db.Column(db.Integer, nullable=True)   # 1-10; None = ranked but outside top 10
    ranking_score = db.Column(db.Float, default=0.0)
    last_updated = db.Column(db.DateTime, default=_now)
    last_fight_date = db.Column(db.DateTime, nullable=True)

    bug = db.relationship('Bug', backref=db.backref('tier_ranking_entry', uselist=False))

    __table_args__ = (db.UniqueConstraint('tier', 'bug_id', name='uq_tier_bug_ranking'),)


class TitleFight(db.Model):
    """A scheduled championship title fight."""
    __tablename__ = 'title_fight'

    id = db.Column(db.Integer, primary_key=True)
    tier = db.Column(db.String(20), nullable=False)
    championship_id = db.Column(db.Integer, db.ForeignKey('tier_championship.id'), nullable=False)
    challenger_bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=True)
    scheduled_date = db.Column(db.DateTime, nullable=False)
    bid_closes_at = db.Column(db.DateTime, nullable=False)
    # bidding → locked (challenger chosen) → completed | cancelled
    status = db.Column(db.String(20), default='bidding')
    battle_id = db.Column(db.Integer, db.ForeignKey('battle.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=_now)

    championship = db.relationship('TierChampionship', backref='title_fights')
    challenger = db.relationship('Bug', foreign_keys=[challenger_bug_id],
                                 backref='title_fight_challenges')
    battle = db.relationship('Battle')


class TitleBid(db.Model):
    """An AP bid by a contender for the upcoming title shot."""
    __tablename__ = 'title_bid'

    id = db.Column(db.Integer, primary_key=True)
    fight_id = db.Column(db.Integer, db.ForeignKey('title_fight.id'), nullable=False)
    bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)          # AP bid amount
    contender_rank = db.Column(db.Integer, nullable=False)  # rank at time of bid (1–3)
    min_required = db.Column(db.Integer, nullable=False)    # minimum AP for that rank
    placed_at = db.Column(db.DateTime, default=_now)
    won_bid = db.Column(db.Boolean, default=False)

    fight = db.relationship('TitleFight', backref='bids')
    bug = db.relationship('Bug', backref='title_bids')
    user = db.relationship('User', backref='title_bids')

    __table_args__ = (db.UniqueConstraint('fight_id', 'bug_id', name='uq_fight_bug_bid'),)


class ContenderCallout(db.Model):
    """A ranked contender challenging another for a ranking bout."""
    __tablename__ = 'contender_callout'

    id = db.Column(db.Integer, primary_key=True)
    tier = db.Column(db.String(20), nullable=False)
    challenger_bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    target_bug_id = db.Column(db.Integer, db.ForeignKey('bug.id'), nullable=False)
    # pending → accepted → completed | declined | expired
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=_now)
    expires_at = db.Column(db.DateTime, nullable=False)   # 7 days to respond
    battle_id = db.Column(db.Integer, db.ForeignKey('battle.id'), nullable=True)

    challenger = db.relationship('Bug', foreign_keys=[challenger_bug_id],
                                 backref='callouts_issued')
    target = db.relationship('Bug', foreign_keys=[target_bug_id],
                             backref='callouts_received')
    battle = db.relationship('Battle')
