"""
Enhanced Battle Engine with XFactor Integration
Uses visible stats + hidden xfactor for more interesting battles
"""

from datetime import datetime
from typing import Optional
from app import db
from app.models import Battle, Bug, BugRival
from app.services.visual_lore_generator import generate_lore_enhanced_battle_narrative
from app.services.achievements import award_battle_achievements
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
        award_battle_achievements(winner, bug2 if winner.id == bug1.id else bug1)

    db.session.add(battle)
    _track_rival_encounter(bug1, bug2, winner)
    db.session.commit()

    return battle


def _track_rival_encounter(bug1: Bug, bug2: Bug, winner: Optional[Bug] = None) -> None:
    """Record a rival encounter and update per-side win counts."""
    b1_id, b2_id = sorted([bug1.id, bug2.id])
    rival = BugRival.query.filter_by(bug1_id=b1_id, bug2_id=b2_id).first()
    if rival:
        rival.encounter_count += 1
        rival.last_encounter_at = datetime.utcnow()
        if winner:
            if winner.id == b1_id:
                rival.bug1_wins = (rival.bug1_wins or 0) + 1
            else:
                rival.bug2_wins = (rival.bug2_wins or 0) + 1
    else:
        b1w = 1 if (winner and winner.id == b1_id) else 0
        b2w = 1 if (winner and winner.id == b2_id) else 0
        rival = BugRival(bug1_id=b1_id, bug2_id=b2_id, bug1_wins=b1w, bug2_wins=b2w)
        db.session.add(rival)


def determine_winner_with_xfactor(bug1: Bug, bug2: Bug) -> Optional[Bug]:
    """Determine winner using the full 6-stat system + xfactor (hidden).

    Stat roles:
      attack   — raw strike force (weight 2.0)
      defense  — structural protection (weight 1.5)
      speed    — agility / evasion (weight 1.2)
      lethality — weapon/venom potency; AMPLIFIES type advantage when > 50 (weight 1.0)
      grip      — engagement control; counters opponent speed advantage (weight 0.8)
      cunning   — tactical instinct; REDUCES type disadvantage when > 50 (weight 0.7)
    """
    def _s(b: Bug, attr: str, default: int = 50) -> int:
        return max(1, getattr(b, attr, default) or default)

    def base_power(b: Bug) -> float:
        return (
            _s(b, 'attack', 5) * 2.0
            + _s(b, 'defense', 5) * 1.5
            + _s(b, 'speed', 5) * 1.2
            + _s(b, 'lethality') * 1.0
            + _s(b, 'grip') * 0.8
            + _s(b, 'cunning') * 0.7
        )

    bug1_power = base_power(bug1)
    bug2_power = base_power(bug2)

    atk1 = getattr(bug1, 'attack_type', None)
    def2 = getattr(bug2, 'defense_type', None)
    atk2 = getattr(bug2, 'attack_type', None)
    def1 = getattr(bug1, 'defense_type', None)

    m1 = get_matchup_multiplier(atk1, def2)
    m2 = get_matchup_multiplier(atk2, def1)

    # Cunning: recover part of a type disadvantage (biological tactical instinct)
    # max cunning (100) halves the deficit; cunning 50 = no recovery
    c1, c2 = _s(bug1, 'cunning'), _s(bug2, 'cunning')
    if m1 < 1.0:
        m1 += ((c1 - 50) / 100.0) * (1.0 - m1)   # positive only when cunning > 50
    if m2 < 1.0:
        m2 += ((c2 - 50) / 100.0) * (1.0 - m2)

    # Lethality: amplify a type advantage beyond the base multiplier
    # lethality 50 = unchanged; 100 = doubles the bonus; 25 = halves it
    l1, l2 = _s(bug1, 'lethality'), _s(bug2, 'lethality')
    if m1 > 1.0:
        m1 = 1.0 + (m1 - 1.0) * (l1 / 50.0)
    if m2 > 1.0:
        m2 = 1.0 + (m2 - 1.0) * (l2 / 50.0)

    bug1_modifier = m1
    bug2_modifier = m2

    # Size multipliers (size-agnostic attacks skip size math)
    s1, s2 = get_size_multipliers(
        getattr(bug1, 'size_class', None),
        getattr(bug2, 'size_class', None),
        attack_type_a=atk1,
        attack_type_b=atk2,
    )
    bug1_modifier *= s1
    bug2_modifier *= s2

    # Grip: engagement control bonus — high grip vs. low grip opponent
    # Scales ±8%; also flattens opponent's raw speed advantage in a grapple
    g1, g2 = _s(bug1, 'grip'), _s(bug2, 'grip')
    grip_delta_1 = (g1 - g2) / 100.0   # -1 to +1
    grip_delta_2 = -grip_delta_1
    bug1_modifier *= 1.0 + grip_delta_1 * 0.08
    bug2_modifier *= 1.0 + grip_delta_2 * 0.08

    # Rivalry: rivals have studied each other — each bug's biggest weapon is anticipated
    # and countered, reducing its effective contribution by 10%.
    b1_id, b2_id = sorted([bug1.id, bug2.id])
    rival = BugRival.query.filter_by(bug1_id=b1_id, bug2_id=b2_id).first()
    if rival and rival.encounter_count >= 2:
        for bug, is_bug1 in ((bug1, True), (bug2, False)):
            dom_contribution = max(
                _s(bug, 'attack', 5) * 2.0,
                _s(bug, 'defense', 5) * 1.5,
                _s(bug, 'speed', 5) * 1.2,
                _s(bug, 'lethality') * 1.0,
                _s(bug, 'grip') * 0.8,
                _s(bug, 'cunning') * 0.7,
            )
            penalty = dom_contribution * 0.10
            if is_bug1:
                bug1_power -= penalty
            else:
                bug2_power -= penalty

    bug1_power *= bug1_modifier
    bug2_power *= bug2_modifier

    # XFactor: hidden ±10% (admin-only knowledge)
    bug1_power *= 1.0 + (bug1.xfactor * 0.02)
    bug2_power *= 1.0 + (bug2.xfactor * 0.02)

    # Tiny random factor — keeps identical matchups interesting
    bug1_power *= random.uniform(0.98, 1.02)
    bug2_power *= random.uniform(0.98, 1.02)

    if abs(bug1_power) < 1e-9 and abs(bug2_power) < 1e-9:
        return None
    if abs(bug1_power - bug2_power) <= 1e-3:
        return None

    return bug1 if bug1_power > bug2_power else bug2


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
    def _display_power(b):
        return (
            (b.attack or 0) + (b.defense or 0) + (b.speed or 0)
            + (getattr(b, 'lethality', 50) or 50)
            + (getattr(b, 'grip', 50) or 50)
            + (getattr(b, 'cunning', 50) or 50)
        )
    bug1_power = _display_power(bug1)
    bug2_power = _display_power(bug2)
    
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


def visible_win_summary(battle: Battle) -> str:
    """Explain the visible battle outcome without exposing hidden xfactor."""
    if not battle.winner:
        return "The visible matchup was too close to call, ending in a draw."

    stats = calculate_battle_stats(battle.bug1, battle.bug2)
    winner = battle.winner
    loser = battle.bug2 if winner.id == battle.bug1_id else battle.bug1
    winner_effective = stats['predicted_bug1_effective'] if winner.id == battle.bug1_id else stats['predicted_bug2_effective']
    loser_effective = stats['predicted_bug2_effective'] if winner.id == battle.bug1_id else stats['predicted_bug1_effective']

    if winner_effective > loser_effective:
        return f"{winner.nickname} had the stronger visible matchup profile, edging out {loser.nickname} on stats and type advantages."
    if winner.speed > loser.speed:
        return f"{winner.nickname} appears to have won through speed and initiative despite a close visible matchup."
    if winner.attack > loser.attack:
        return f"{winner.nickname} appears to have won by applying stronger offensive pressure."
    if winner.defense > loser.defense:
        return f"{winner.nickname} appears to have survived the exchange through better defenses."
    return f"{winner.nickname} won a close fight where the visible stats were nearly even."


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
