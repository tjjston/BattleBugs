"""Bug condition modifiers — applied after LLM stat generation.

Conditions detected by the classifier affect stats, flair, and lore.
Dead bugs go through Zombugification (33% fail chance built into caller).
"""
import random

CONDITION_MODIFIERS = {
    'dead': {
        'multipliers': {
            'attack': 1.10, 'defense': 1.10, 'speed': 0.85,
            'lethality': 1.15, 'grip': 0.80, 'cunning': 0.70,
        },
        'flair': '🧟 Zombug',
        'lore': (
            'Risen from the dead, this specimen enters the arena with an eerie, '
            'unstoppable ferocity. Its natural weapons grow more lethal in death, '
            'but the body is brittle and the tactical mind is long gone.'
        ),
    },
    'squashed': {
        'multipliers': {
            'attack': 0.65, 'defense': 0.40, 'speed': 0.55,
            'lethality': 0.80, 'grip': 0.65, 'cunning': 0.90,
        },
        'flair': '💀 Battle-Worn',
        'lore': (
            'This bug arrived bearing the marks of a catastrophic crushing incident. '
            'Its armor is severely compromised, its movements labored and pained — '
            'yet against all odds, it refuses to quit the arena.'
        ),
    },
    'damaged_wings': {
        'multipliers': {'speed': 0.75, 'cunning': 0.90},
        'flair': '🩹 Grounded',
        'lore': (
            'Grounded by torn or missing wings, this bug can no longer take to the air. '
            'Slower, robbed of a key escape route, it must fight with cunning rather than flight.'
        ),
    },
    'damaged_legs': {
        'multipliers': {'speed': 0.80, 'grip': 0.70},
        'flair': '🦿 Limping',
        'lore': (
            'Bearing missing or broken limbs, this bug moves with a halting, uneven gait. '
            'Its grip strength is reduced, but sheer will keeps it upright and fighting.'
        ),
    },
    'damaged': {
        'multipliers': {'speed': 0.85, 'grip': 0.85},
        'flair': '⚔️ Scarred',
        'lore': (
            'Visibly damaged and scarred, this bug carries its wounds openly into the arena. '
            'Every mark tells the story of a survivor.'
        ),
    },
    'alive': {
        'multipliers': {},
        'flair': None,
        'lore': None,
    },
}

ZOMBUG_FAIL_CHANCE = 0.33

_STAT_NAMES = ('attack', 'defense', 'speed', 'lethality', 'grip', 'cunning')


def roll_zombug_success() -> bool:
    """67% chance of successful zombugification."""
    return random.random() >= ZOMBUG_FAIL_CHANCE


def apply_condition_modifiers(bug, condition: str, llm_notes: str | None = None) -> str | None:
    """Apply condition stat multipliers to bug in-place.

    Returns the lore string to store (prefers llm_notes if provided).
    Stats are clamped to [1, 100] after multiplication.
    """
    meta = CONDITION_MODIFIERS.get(condition) or CONDITION_MODIFIERS['alive']
    for stat, mult in meta['multipliers'].items():
        current = getattr(bug, stat, 50) or 50
        setattr(bug, stat, max(1, min(100, int(round(current * mult)))))

    if meta.get('flair'):
        bug.flair = meta['flair']

    bug.condition = condition
    lore = llm_notes if llm_notes else meta.get('lore')
    return lore


def condition_display(condition: str) -> dict:
    """Return display metadata (label, badge colour) for a condition string."""
    return {
        'dead':          {'label': '🧟 Zombug',       'color': 'success'},
        'squashed':      {'label': '💀 Battle-Worn',  'color': 'danger'},
        'damaged_wings': {'label': '🩹 Grounded',     'color': 'warning'},
        'damaged_legs':  {'label': '🦿 Limping',      'color': 'warning'},
        'damaged':       {'label': '⚔️ Scarred',      'color': 'secondary'},
        'alive':         {'label': '✅ Healthy',       'color': 'light'},
    }.get(condition, {'label': condition, 'color': 'secondary'})
