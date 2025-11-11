from typing import Optional, Dict

from app import db
from app.models import Battle, Bug
from app.services.llm_service import generate_battle_narrative
import random


# Static advantage tables used by multiple functions
MATCHUP_ADVANTAGES = {
    # (attack_type, defense_type): multiplier
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
    """Run a single battle simulation between two Bug objects and persist a Battle record.

    Returns the created Battle SQLAlchemy model instance. A draw is represented by
    winner_id = None on the Battle model.
    """
    winner = determine_winner(bug1, bug2)
    narrative = generate_battle_narrative(bug1, bug2, winner)

    battle = Battle(
        bug1_id=bug1.id,
        bug2_id=bug2.id,
        winner_id=winner.id if winner else None,
        battle_date=db.func.current_timestamp(),
        narrative=narrative,
        tournament_id=tournament_id,
        round_number=round_number,
    )

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


def determine_winner(bug1: Bug, bug2: Bug) -> Optional[Bug]:
    """Compute power for each bug and decide a winner.

    Returns the winning Bug, or None for a draw.
    """
    # Base power with weights (tweak weights here to tune balance)
    def base_power(b: Bug) -> float:
        return (
            b.attack * 2.0
            + b.defense * 1.5
            + b.speed * 1.2
            + b.special_attack
            + b.special_defense
            + b.health * 0.5
            + (getattr(b, 'xfactor', 0) * 0.1)
        )

    bug1_power = base_power(bug1)
    bug2_power = base_power(bug2)

    # Apply matchup and size modifiers
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

    # Apply small randomness but keep high precision to reduce spurious draws
    bug1_power *= random.uniform(0.97, 1.03)
    bug2_power *= random.uniform(0.97, 1.03)

    # If both powers are effectively zero, it's a draw
    if abs(bug1_power) < 1e-9 and abs(bug2_power) < 1e-9:
        return None

    # Decide winner with a small epsilon to avoid ties from floating rounding
    eps = 1e-3  # 0.001 absolute tolerance (tuneable)
    diff = bug1_power - bug2_power
    if abs(diff) <= eps:
        return None
    return bug1 if diff > 0 else bug2


def get_matchup_notes(bug1: Bug, bug2: Bug):
    notes = []
    if (getattr(bug1, 'attack_type', None), getattr(bug2, 'defense_type', None)) in MATCHUP_ADVANTAGES:
        advantage = MATCHUP_ADVANTAGES[(bug1.attack_type, bug2.defense_type)]
        if advantage > 1:
            notes.append(f"{bug1.name}'s {bug1.attack_type} attacks are effective against {bug2.defense_type} defenses!")

    if (getattr(bug2, 'attack_type', None), getattr(bug1, 'defense_type', None)) in MATCHUP_ADVANTAGES:
        advantage = MATCHUP_ADVANTAGES[(bug2.attack_type, bug1.defense_type)]
        if advantage > 1:
            notes.append(f"{bug2.name}'s {bug2.attack_type} attacks exploit {bug1.name}'s {bug1.defense_type}!")

    return notes


def calculate_battle_stats(bug1: Bug, bug2: Bug) -> Dict:
    """Return a dict of display-friendly stats for UI or debugging."""
    bug1_power = (
        bug1.attack
        + bug1.defense
        + bug1.speed
        + bug1.special_attack
        + bug1.special_defense
        + bug1.health
        + getattr(bug1, 'xfactor', 0)
    )
    bug2_power = (
        bug2.attack
        + bug2.defense
        + bug2.speed
        + bug2.special_attack
        + bug2.special_defense
        + bug2.health
        + getattr(bug2, 'xfactor', 0)
    )

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
