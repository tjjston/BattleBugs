from datetime import datetime, timezone, timezone

from app import db
from app.models import Bug, BugAchievement
from app.services.economy import (
    ACHIEVEMENT_REWARDS,
    SUBMISSION_REWARD,
    UNIQUE_SPECIES_REWARD,
    award_currency,
)


def award_achievement(bug, achievement_type: str, name: str, icon: str, description: str, rarity: str = 'common') -> bool:
    existing = BugAchievement.query.filter_by(
        bug_id=bug.id,
        achievement_type=achievement_type,
    ).first()
    if existing:
        return False

    achievement = BugAchievement(
        bug_id=bug.id,
        achievement_type=achievement_type,
        achievement_name=name,
        achievement_icon=icon,
        description=description,
        rarity=rarity,
    )
    db.session.add(achievement)
    award_currency(
        bug.owner,
        ACHIEVEMENT_REWARDS.get(achievement_type, 0),
        f'achievement:{achievement_type}',
        'bug_achievement',
        bug.id,
    )
    return True


_TIER_BADGES = {
    'uber': ('tier_first_uber', 'Legendary Collector', '🔴', 'First Legendary tier bug collected', 'rare'),
    'ou':   ('tier_first_ou',   'Elite Collector',     '🟠', 'First Elite tier bug collected',     'uncommon'),
    'uu':   ('tier_first_uu',   'Strong Collector',    '🔵', 'First Strong tier bug collected',     'uncommon'),
    'ru':   ('tier_first_ru',   'Rising Collector',    '🩵', 'First Rising tier bug collected',     'common'),
    'nu':   ('tier_first_nu',   'Newcomer Collector',  '⚫', 'First Newcomer tier bug collected',   'common'),
    'zu':   ('tier_first_zu',   'Zero Collector',      '🟤', 'First Zero tier bug collected',       'common'),
}

_ATTACK_BADGES = {
    'piercing':  ('atk_first_piercing',  'Sharp Collector',    '⚔️',  'First piercing-type bug collected',  'common'),
    'crushing':  ('atk_first_crushing',  'Crusher Collector',  '💥',  'First crushing-type bug collected',  'common'),
    'slashing':  ('atk_first_slashing',  'Blade Collector',    '🔪',  'First slashing-type bug collected',  'common'),
    'venom':     ('atk_first_venom',     'Venom Collector',    '☠️',  'First venom-type bug collected',     'uncommon'),
    'chemical':  ('atk_first_chemical',  'Chem Collector',     '⚗️',  'First chemical-type bug collected',  'uncommon'),
    'grappling': ('atk_first_grappling', 'Grappler Collector', '🤼',  'First grappling-type bug collected', 'common'),
}

_DEFENSE_BADGES = {
    'hard_shell':      ('def_first_hard_shell',      'Shell Collector',    '🛡️',  'First hard-shell bug collected',      'common'),
    'segmented_armor': ('def_first_segmented_armor', 'Armor Collector',    '🔗',  'First segmented-armor bug collected', 'common'),
    'evasive':         ('def_first_evasive',         'Ghost Collector',    '💨',  'First evasive bug collected',         'common'),
    'hairy_spiny':     ('def_first_hairy_spiny',     'Spiny Collector',    '🦔',  'First hairy/spiny bug collected',     'common'),
    'toxic_skin':      ('def_first_toxic_skin',      'Toxic Collector',    '☢️',  'First toxic-skin bug collected',      'uncommon'),
    'thick_hide':      ('def_first_thick_hide',      'Hide Collector',     '🦏',  'First thick-hide bug collected',      'common'),
}

_SIZE_BADGES = {
    'tiny':    ('size_first_tiny',    'Tiny Terror',   '🔬', 'First tiny bug collected',    'common'),
    'small':   ('size_first_small',   'Small Fry',     '🐜', 'First small bug collected',   'common'),
    'medium':  ('size_first_medium',  'Mid Ranger',    '🐛', 'First medium bug collected',  'common'),
    'large':   ('size_first_large',   'Big Bug',       '🦗', 'First large bug collected',   'uncommon'),
    'massive': ('size_first_massive', 'Goliath Found', '🦂', 'First massive bug collected', 'rare'),
}


def _award_collector_badges(bug) -> None:
    """Award first-of-kind collector badges to the bug's owner based on tier/attack/defense/size."""
    owner = bug.owner
    if not owner:
        return

    # Check via BugAchievement on any of the owner's bugs
    from app.models import Bug as _Bug
    owner_bug_ids = [b.id for b in _Bug.query.filter_by(user_id=owner.id).all()]

    def _owner_has(atype):
        return BugAchievement.query.filter(
            BugAchievement.bug_id.in_(owner_bug_ids),
            BugAchievement.achievement_type == atype,
        ).first() is not None

    if bug.tier and bug.tier in _TIER_BADGES:
        atype, name, icon, desc, rarity = _TIER_BADGES[bug.tier]
        if not _owner_has(atype):
            award_achievement(bug, atype, name, icon, desc, rarity)

    if bug.attack_type and bug.attack_type in _ATTACK_BADGES:
        atype, name, icon, desc, rarity = _ATTACK_BADGES[bug.attack_type]
        if not _owner_has(atype):
            award_achievement(bug, atype, name, icon, desc, rarity)

    if bug.defense_type and bug.defense_type in _DEFENSE_BADGES:
        atype, name, icon, desc, rarity = _DEFENSE_BADGES[bug.defense_type]
        if not _owner_has(atype):
            award_achievement(bug, atype, name, icon, desc, rarity)

    if bug.size_class and bug.size_class in _SIZE_BADGES:
        atype, name, icon, desc, rarity = _SIZE_BADGES[bug.size_class]
        if not _owner_has(atype):
            award_achievement(bug, atype, name, icon, desc, rarity)


def award_submission_achievements(bug) -> None:
    award_currency(
        bug.owner,
        SUBMISSION_REWARD,
        'approved_bug_submission',
        'bug',
        bug.id,
    )
    award_achievement(
        bug,
        'first_submission',
        'Arena Arrival',
        '★',
        'Entered the BattleBugs arena.',
    )
    _award_collector_badges(bug)
    if bug.species_id:
        # Per-user unique species bonus
        existing_species_count = Bug.query.filter(
            Bug.user_id == bug.user_id,
            Bug.species_id == bug.species_id,
            Bug.id != bug.id,
        ).count()
        if existing_species_count == 0:
            award_currency(
                bug.owner,
                UNIQUE_SPECIES_REWARD,
                'unique_species_submission',
                'bug',
                bug.id,
            )
            award_achievement(
                bug,
                'species_discovery',
                'Cataloged Challenger',
                '◇',
                'Contributed to the species collection.',
            )

        # Global first-ever pioneer bonus (across all users)
        global_species_count = Bug.query.filter(
            Bug.species_id == bug.species_id,
            Bug.id != bug.id,
        ).count()
        if global_species_count == 0:
            award_currency(
                bug.owner,
                ACHIEVEMENT_REWARDS.get('species_pioneer', 50),
                'achievement:species_pioneer',
                'bug',
                bug.id,
            )
            award_achievement(
                bug,
                'species_pioneer',
                'World First!',
                '🌍',
                'First ever to bring this species into the arena.',
                rarity='rare',
            )


def award_battle_achievements(winner, loser=None) -> None:
    if not winner:
        return
    award_achievement(
        winner,
        'first_win',
        'First Victory',
        '🏅',
        'Won a first recorded battle.',
    )
    wins = winner.wins or 0
    if wins >= 3:
        newly = award_achievement(
            winner,
            'three_wins',
            'Arena Regular',
            '🥉',
            'Reached three battle wins.',
            rarity='uncommon',
        )
        if newly:
            _context_stat_boost(winner, loser, amount=2)
    if wins >= 5:
        newly = award_achievement(
            winner,
            'five_wins',
            'Proven Gladiator',
            '🥈',
            'Reached five battle wins.',
            rarity='rare',
        )
        if newly:
            _context_stat_boost(winner, loser, amount=2)
    if wins >= 10:
        newly = award_achievement(
            winner,
            'ten_wins',
            'Decade of Dominance',
            '🥇',
            'Reached ten battle wins.',
            rarity='rare',
        )
        if newly:
            _context_stat_boost(winner, loser, amount=3)
        _retire_bug(winner)


def award_tournament_champion(bug) -> None:
    award_achievement(
        bug,
        'tournament_champion',
        'Tournament Champion',
        'T',
        'Won a tournament.',
        rarity='rare',
    )


def award_lore_participation(bug) -> None:
    award_achievement(
        bug,
        'lore_magnet',
        'Lore Magnet',
        '📖',
        'Inspired community lore.',
        rarity='uncommon',
    )


def _context_stat_boost(winner, loser, amount: int) -> str:
    """Choose which stat to boost based on what the loser was strongest in.

    - Loser dominant attack  → winner gains defense (survived the onslaught)
    - Loser dominant defense → winner gains attack  (learned to pierce armor)
    - Loser dominant speed   → winner gains speed   (matched their pace)
    - No loser info          → boost winner's weakest stat
    """
    if loser is not None:
        loser_stats = {
            'attack': loser.attack or 0,
            'defense': loser.defense or 0,
            'speed': loser.speed or 0,
        }
        dominant = max(loser_stats, key=loser_stats.get)
        stat = {'attack': 'defense', 'defense': 'attack', 'speed': 'speed'}[dominant]
    else:
        winner_stats = {
            'attack': winner.attack or 0,
            'defense': winner.defense or 0,
            'speed': winner.speed or 0,
        }
        stat = min(winner_stats, key=winner_stats.get)

    _apply_stat_growth(winner, stat=stat, amount=amount)
    return stat


def _apply_stat_growth(bug, stat: str, amount: int, reason: str = '') -> None:
    """Permanently boost one stat by `amount`, capped at 100. Tracks total growth on bug."""
    current = getattr(bug, stat, 0) or 0
    new_val = min(current + amount, 100)
    setattr(bug, stat, new_val)
    bug.stat_growth = (bug.stat_growth or 0) + (new_val - current)
    db.session.add(bug)


def _retire_bug(bug) -> None:
    if bug.is_retired:
        return
    bug.is_retired = True
    bug.retired_at = datetime.now(timezone.utc)
    db.session.add(bug)
    award_achievement(
        bug,
        'arena_legend',
        'Arena Legend',
        '🏆',
        'Retired with 10+ wins — a true champion.',
        rarity='rare',
    )
    award_currency(
        bug.owner,
        ACHIEVEMENT_REWARDS.get('arena_legend', 200),
        'achievement:arena_legend',
        'bug',
        bug.id,
    )
