"""
Enhanced Battle Engine with XFactor Integration
Uses visible stats + hidden xfactor for more interesting battles
"""

from typing import Optional
from app import db
from app.models import Battle, Bug
from app.routes.visual_lore_generator import generate_lore_enhanced_battle_narrative
import random

# Static advantage tables
MATCHUP_ADVANTAGES = {
    ('piercing', 'soft'): 1.5,
    ('piercing', 'hard_shell'): 0.6,
    ('crushing', 'hard_shell'): 1.4,
    ('crushing', 'agile'): 0.7,
    ('slashing', 'soft'): 1.3,
    ('slashing', 'thick_carapace'): 0.8,
    ('venom', 'agile'): 0.7,
    ('venom', 'large'): 1.3,
}

SIZE_ADVANTAGES = {
    ('large', 'tiny'): 1.3,
    ('tiny', 'large'): 0.8,
    ('medium', 'tiny'): 1.15,
}


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
    
    matchup_key_1 = (getattr(bug1, 'attack_type', None), getattr(bug2, 'defense_type', None))
    matchup_key_2 = (getattr(bug2, 'attack_type', None), getattr(bug1, 'defense_type', None))
    bug1_modifier *= MATCHUP_ADVANTAGES.get(matchup_key_1, 1.0)
    bug2_modifier *= MATCHUP_ADVANTAGES.get(matchup_key_2, 1.0)
    
    size_key_1 = (getattr(bug1, 'size_class', None), getattr(bug2, 'size_class', None))
    size_key_2 = (getattr(bug2, 'size_class', None), getattr(bug1, 'size_class', None))
    bug1_modifier *= SIZE_ADVANTAGES.get(size_key_1, 1.0)
    bug2_modifier *= SIZE_ADVANTAGES.get(size_key_2, 1.0)
    
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
    
    if (getattr(bug1, 'attack_type', None), getattr(bug2, 'defense_type', None)) in MATCHUP_ADVANTAGES:
        advantage = MATCHUP_ADVANTAGES[(bug1.attack_type, bug2.defense_type)]
        if advantage > 1:
            notes.append(f"{bug1.nickname}'s {bug1.attack_type} attacks are effective!")
    
    if (getattr(bug2, 'attack_type', None), getattr(bug1, 'defense_type', None)) in MATCHUP_ADVANTAGES:
        advantage = MATCHUP_ADVANTAGES[(bug2.attack_type, bug1.defense_type)]
        if advantage > 1:
            notes.append(f"{bug2.nickname}'s {bug2.attack_type} attacks exploit {bug1.nickname}'s defenses!")
    
    return notes


def calculate_battle_stats(bug1: Bug, bug2: Bug) -> dict:
    """
    Return display-friendly stats (DOES NOT reveal xfactor to users)
    """
    bug1_power = bug1.attack + bug1.defense + bug1.speed
    bug2_power = bug2.attack + bug2.defense + bug2.speed
    
    stats = {
        'bug1_power': bug1_power,
        'bug2_power': bug2_power,
        'bug1_advantage': None,
        'bug2_advantage': None,
        'bug1_modifier': 1.0,
        'bug2_modifier': 1.0,
        'matchup_notes': get_matchup_notes(bug1, bug2),
    }
    
    if bug1.speed > bug2.speed:
        stats['bug1_advantage'] = 'Speed'
    if bug2.attack > bug1.attack:
        stats['bug2_advantage'] = 'Attack'
    
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