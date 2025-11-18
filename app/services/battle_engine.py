"""
Enhanced Battle Engine with XFactor Integration
Uses visible stats + hidden xfactor for more interesting battles
"""

from typing import Optional
from app import db
from app.models import Battle, Bug
from app.services.visual_lore_generator import generate_lore_enhanced_battle_narrative
import random

# Combat type system (offensive -> defensive multipliers)
# Offensive types: piercing, crushing, slashing, venom, chemical, grappling
# Defensive types: hard_shell, segmented_armor, evasive, hairy_spiny, toxic_skin, thick_hide
MATCHUP_MATRIX = {
    'piercing': {
        'hard_shell': 1.5, 'segmented_armor': 1.0, 'evasive': 0.7,
        'hairy_spiny': 1.0, 'toxic_skin': 1.5, 'thick_hide': 0.7
    },
    'crushing': {
        'hard_shell': 1.5, 'segmented_armor': 0.7, 'evasive': 1.0,
        'hairy_spiny': 1.0, 'toxic_skin': 0.7, 'thick_hide': 1.5
    },
    'slashing': {
        'hard_shell': 0.7, 'segmented_armor': 1.5, 'evasive': 1.5,
        'hairy_spiny': 0.7, 'toxic_skin': 1.0, 'thick_hide': 1.0
    },
    'venom': {
        'hard_shell': 1.0, 'segmented_armor': 1.5, 'evasive': 1.0,
        'hairy_spiny': 0.7, 'toxic_skin': 0.7, 'thick_hide': 1.5
    },
    'chemical': {
        'hard_shell': 1.0, 'segmented_armor': 1.0, 'evasive': 1.5,
        'hairy_spiny': 1.5, 'toxic_skin': 0.7, 'thick_hide': 0.7
    },
    'grappling': {
        'hard_shell': 0.7, 'segmented_armor': 0.7, 'evasive': 1.5,
        'hairy_spiny': 1.5, 'toxic_skin': 1.0, 'thick_hide': 1.0
    }
}

# Size classes (ordered)
SIZE_ORDER = ['tiny', 'small', 'medium', 'large', 'massive']

# Base size modifiers provided by designer (explicit pairs)
SIZE_BASE_MODIFIER = {
    ('massive', 'tiny'): 1.5,
    ('massive', 'small'): 1.3,
    ('massive', 'medium'): 1.15,
    ('large', 'tiny'): 1.4,
    ('large', 'small'): 1.25,
    ('large', 'medium'): 1.1,
    ('medium', 'tiny'): 1.3,
    ('medium', 'small'): 1.15,
    ('small', 'tiny'): 1.2,
    ('tiny', 'massive'): 0.7,
    ('tiny', 'large'): 0.75,
    ('tiny', 'medium'): 0.8,
    ('small', 'massive'): 0.75,
    ('small', 'large'): 0.8,
    ('small', 'medium'): 0.85,
    ('medium', 'large'): 0.9,
    ('medium', 'massive'): 0.85,
    ('large', 'massive'): 0.9,
}

# Define which offensive types depend on size and which are size-agnostic
# Size-dependent attacks gain/lose from size differences (e.g., crushing, grappling)
# Size-agnostic attacks ignore size in their effect (e.g., venom, chemical)
SIZE_DEPENDENT_ATTACKS = {'crushing', 'grappling', 'piercing', 'slashing'}
SIZE_AGNOSTIC_ATTACKS = {'venom', 'chemical'}
def get_matchup_multiplier(attack_type: str, defense_type: str) -> float:
    """Return multiplier for attack_type vs defense_type using MATCHUP_MATRIX.
    Falls back to 1.0 for unknown types."""
    if not attack_type or not defense_type:
        return 1.0
    attack = (attack_type or '').lower()
    defense = (defense_type or '').lower()
    return MATCHUP_MATRIX.get(attack, {}).get(defense, 1.0)


def _normalize_size(s: str) -> Optional[str]:
    if not s:
        return None
    s = s.lower()
    # Accept synonyms
    if s == 'giant':
        return 'massive'
    return s if s in SIZE_ORDER else None


def get_size_multipliers(size_a: str, size_b: str, attack_type_a: Optional[str] = None, attack_type_b: Optional[str] = None) -> tuple[float, float]:
    """Return (mult_a, mult_b) based on size class and (optionally) attack types.

    Behavior:
    - If an attack type is size-agnostic (e.g., venom/chemical), that attack ignores size modifiers.
    - If size-pair explicit mapping exists in `SIZE_BASE_MODIFIER`, it is used.
    - Otherwise, fallback to symmetric diff-based modifiers.
    """
    a = _normalize_size(size_a)
    b = _normalize_size(size_b)

    # Unknown sizes -> neutral
    if a is None or b is None:
        return 1.0, 1.0

    # If attack types explicitly ignore size, respect that
    atk_a = (attack_type_a or '').lower() if attack_type_a else None
    atk_b = (attack_type_b or '').lower() if attack_type_b else None

    # If both attacks are size-agnostic, no size modifiers apply
    if (atk_a in SIZE_AGNOSTIC_ATTACKS) and (atk_b in SIZE_AGNOSTIC_ATTACKS):
        return 1.0, 1.0

    # Compute default diff-based multipliers (fallback)
    ia = SIZE_ORDER.index(a)
    ib = SIZE_ORDER.index(b)
    diff = ia - ib
    def default_for_diff(d):
        if d == 0:
            return 1.0
        if d == 1:
            return 1.15
        if d == 2:
            return 1.30
        if d >= 3:
            return 1.40
        if d == -1:
            return 1.0 / 1.15
        if d == -2:
            return 1.0 / 1.30
        if d <= -3:
            return 1.0 / 1.40
        return 1.0

    # Try explicit mapping first
    explicit_a = SIZE_BASE_MODIFIER.get((a, b))
    explicit_b = SIZE_BASE_MODIFIER.get((b, a))

    if explicit_a is not None or explicit_b is not None:
        # If one direction missing, try reciprocal of the other or fallback
        if explicit_a is None and explicit_b is not None:
            explicit_a = 1.0 / explicit_b if explicit_b != 0 else 1.0
        if explicit_b is None and explicit_a is not None:
            explicit_b = 1.0 / explicit_a if explicit_a != 0 else 1.0
        mult_a = explicit_a if explicit_a is not None else default_for_diff(diff)
        mult_b = explicit_b if explicit_b is not None else default_for_diff(-diff)
    else:
        mult_a = default_for_diff(diff)
        mult_b = default_for_diff(-diff)

    # If a given attack is size-agnostic, it should not receive the size-based boost/penalty
    if atk_a in SIZE_AGNOSTIC_ATTACKS:
        mult_a = 1.0
    if atk_b in SIZE_AGNOSTIC_ATTACKS:
        mult_b = 1.0

    return round(mult_a, 3), round(mult_b, 3)


def simulate_battle(bug1: Bug, bug2: Bug, tournament_id: Optional[int] = None, round_number: int = 0) -> Battle:
    """
    Run a battle simulation with xfactor integration
    
    The xfactor is SECRET - users never know it exists!
    It subtly influences who wins, making battles more interesting.
    """
    winner = determine_winner_with_xfactor(bug1, bug2)
    
    # Generate lore-enhanced narrative
    narrative = generate_lore_enhanced_battle_narrative(bug1, bug2, winner)

    battle = Battle(
        bug1_id=bug1.id,
        bug2_id=bug2.id,
        winner_id=winner.id if winner else None,
        battle_date=db.func.current_timestamp(),
        narrative=narrative,
        tournament_id=tournament_id,
        round_number=round_number,
    )
    
    # Track if xfactor was significant
    if abs(bug1.xfactor - bug2.xfactor) >= 2.0:
        battle.xfactor_triggered = True
        
        # Which bug had the advantage?
        if winner:
            if winner.id == bug1.id and bug1.xfactor > bug2.xfactor:
                battle.xfactor_details = f"{bug1.nickname}'s hidden advantage: {bug1.visual_lore_items or 'mysterious power'}"
            elif winner.id == bug2.id and bug2.xfactor > bug1.xfactor:
                battle.xfactor_details = f"{bug2.nickname}'s hidden advantage: {bug2.visual_lore_items or 'mysterious power'}"

    # Update win/loss records
    if winner:
        if winner.id == bug1.id:
            bug1.wins = (bug1.wins or 0) + 1
            bug2.losses = (bug2.losses or 0) + 1
        else:
            bug2.wins = (bug2.wins or 0) + 1
            bug1.losses = (bug1.losses or 0) + 1

    db.session.add(battle)
    db.session.commit()

    return battle


def determine_winner_with_xfactor(bug1: Bug, bug2: Bug) -> Optional[Bug]:
    """
    Determine winner using stats + SECRET XFACTOR
    
    The xfactor adds subtle randomness that makes sense narratively
    without players knowing it exists.
    """
    def base_power(b: Bug) -> float:
        """Calculate base power from visible stats"""
        return (
            b.attack * 2.0
            + b.defense * 1.5
            + b.speed * 1.2
            + (b.special_attack if hasattr(b, 'special_attack') else 0)
            + (b.special_defense if hasattr(b, 'special_defense') else 0)
            + (b.health * 0.5 if hasattr(b, 'health') else 0)
        )
    
    bug1_power = base_power(bug1)
    bug2_power = base_power(bug2)
    
    # Apply matchup modifiers (from attack/defense types if they exist)
    bug1_modifier = 1.0
    bug2_modifier = 1.0
    
    # Matchup multipliers based on attack vs defense types
    atk1 = getattr(bug1, 'attack_type', None)
    def2 = getattr(bug2, 'defense_type', None)
    atk2 = getattr(bug2, 'attack_type', None)
    def1 = getattr(bug1, 'defense_type', None)

    m1 = get_matchup_multiplier(atk1, def2)
    m2 = get_matchup_multiplier(atk2, def1)
    bug1_modifier *= m1
    bug2_modifier *= m2

    # Size multipliers (pass attack types so size-agnostic attacks can ignore size)
    s1, s2 = get_size_multipliers(
        getattr(bug1, 'size_class', None),
        getattr(bug2, 'size_class', None),
        attack_type_a=atk1,
        attack_type_b=atk2,
    )
    bug1_modifier *= s1
    bug2_modifier *= s2
    
    bug1_power *= bug1_modifier
    bug2_power *= bug2_modifier
    
    # XFactor influences power by up to 10% +5.0 xfactor = +10% power boost; -5.0 xfactor = -10% power penalty
    
    xfactor_multiplier_1 = 1.0 + (bug1.xfactor * 0.02)  # -10% to +10%
    xfactor_multiplier_2 = 1.0 + (bug2.xfactor * 0.02)
    
    bug1_power *= xfactor_multiplier_1
    bug2_power *= xfactor_multiplier_2
    
    # Log the xfactor influence (for debugging/admin only)
    print(f"🎲 XFACTOR INFLUENCE:")
    print(f"   {bug1.nickname}: {bug1.xfactor:+.1f} → {xfactor_multiplier_1:.2%} power")
    print(f"   {bug2.nickname}: {bug2.xfactor:+.1f} → {xfactor_multiplier_2:.2%} power")
    # ═══════════════════════════════════════════════════════
    bug1_power *= random.uniform(0.98, 1.02)  # Only ±2% random
    bug2_power *= random.uniform(0.98, 1.02)
    
    # Decide winner
    if abs(bug1_power) < 1e-9 and abs(bug2_power) < 1e-9:
        return None  # Draw
    
    eps = 1e-3
    diff = bug1_power - bug2_power
    
    if abs(diff) <= eps:
        return None  # Draw
    
    return bug1 if diff > 0 else bug2


def get_matchup_notes(bug1: Bug, bug2: Bug):
    """Get visible matchup advantages"""
    notes = []
    
    m1 = get_matchup_multiplier(getattr(bug1, 'attack_type', None), getattr(bug2, 'defense_type', None))
    if m1 > 1.01:
        notes.append(f"{bug1.nickname}'s {getattr(bug1, 'attack_type', 'attack')} attacks are effective!")
    elif m1 < 0.99:
        notes.append(f"{bug1.nickname}'s {getattr(bug1, 'attack_type', 'attack')} attacks struggle against {bug2.nickname}'s defenses.")
    
    m2 = get_matchup_multiplier(getattr(bug2, 'attack_type', None), getattr(bug1, 'defense_type', None))
    if m2 > 1.01:
        notes.append(f"{bug2.nickname}'s {getattr(bug2, 'attack_type', 'attack')} attacks exploit {bug1.nickname}'s defenses!")
    elif m2 < 0.99:
        notes.append(f"{bug2.nickname}'s {getattr(bug2, 'attack_type', 'attack')} attacks struggle against {bug1.nickname}'s defenses.")
    
    return notes


def calculate_battle_stats(bug1: Bug, bug2: Bug) -> dict:
    """
    Return display-friendly stats (DOES NOT reveal xfactor to users)
    """
    bug1_power = bug1.attack + bug1.defense + bug1.speed
    bug2_power = bug2.attack + bug2.defense + bug2.speed
    
    # Compute matchup and size modifiers (visible to users as 'expected advantage')
    atk_mult_1 = get_matchup_multiplier(getattr(bug1, 'attack_type', None), getattr(bug2, 'defense_type', None))
    atk_mult_2 = get_matchup_multiplier(getattr(bug2, 'attack_type', None), getattr(bug1, 'defense_type', None))
    size_mult_1, size_mult_2 = get_size_multipliers(
        getattr(bug1, 'size_class', None),
        getattr(bug2, 'size_class', None),
        attack_type_a=getattr(bug1, 'attack_type', None),
        attack_type_b=getattr(bug2, 'attack_type', None),
    )

    bug1_modifier = atk_mult_1 * size_mult_1
    bug2_modifier = atk_mult_2 * size_mult_2

    stats = {
        'bug1_power': bug1_power,
        'bug2_power': bug2_power,
        'bug1_advantage': None,
        'bug2_advantage': None,
        'bug1_modifier': round(bug1_modifier, 3),
        'bug2_modifier': round(bug2_modifier, 3),
        'matchup_notes': get_matchup_notes(bug1, bug2),
    }
    
    if bug1.speed > bug2.speed:
        stats['bug1_advantage'] = 'Speed'
    if bug2.attack > bug1.attack:
        stats['bug2_advantage'] = 'Attack'

    # Predicted effective power (before secret xfactor/randomness)
    stats['predicted_bug1_effective'] = round(bug1_power * bug1_modifier, 2)
    stats['predicted_bug2_effective'] = round(bug2_power * bug2_modifier, 2)
    
    return stats


def reveal_xfactor_secrets(battle: Battle) -> dict:
    """
    ADMIN ONLY: Reveal xfactor details for a battle
    This is never shown to regular users!
    
    Returns dict with secret battle info
    """
    bug1 = battle.bug1
    bug2 = battle.bug2
    
    return {
        'bug1': {
            'name': bug1.nickname,
            'xfactor': bug1.xfactor,
            'xfactor_reason': bug1.xfactor_reason,
            'visual_items': bug1.visual_lore_items,
            'visual_analysis': bug1.visual_lore_analysis,
        },
        'bug2': {
            'name': bug2.nickname,
            'xfactor': bug2.xfactor,
            'xfactor_reason': bug2.xfactor_reason,
            'visual_items': bug2.visual_lore_items,
            'visual_analysis': bug2.visual_lore_analysis,
        },
        'xfactor_triggered': battle.xfactor_triggered,
        'xfactor_details': battle.xfactor_details,
        'winner': battle.winner.nickname if battle.winner else 'Draw'
    }