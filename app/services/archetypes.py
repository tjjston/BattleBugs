"""Combat archetypes — the framework that gives stat generation a defensible
shape per ecological role.

The LLM picks (archetype, tier). The archetype determines the **shape** of
stats (which are high, which are low). The tier determines the **total
budget**. Together they produce predictable, defensible stats with room for
the LLM to express specimen-specific deviation inside guardrails.

Guardrails
----------
- Each archetype's "shape" is a set of relative weights summing to 1.0.
- Applied at the tier's mid-point budget, each stat gets a base value.
- The LLM is allowed to deviate each stat by ±15 from base — wide enough
  for real specimen-to-specimen variation (so a small mantis genuinely
  differs from a large one), narrow enough that the archetype identity
  still reads (a "Heavy Tank" is still tanky after deviation).
- After deviation, totals are clamped back into the tier band so the bug
  stays in its assigned tier.

Tiers and budgets (mid-point used as the archetype reference):
  ZU  200-260  (mid 230)
  NU  260-320  (mid 290)
  RU  320-400  (mid 360)
  UU  400-480  (mid 440)
  OU  480-540  (mid 510)
  Uber 540-600 (mid 570)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# (lo, hi, midpoint) per tier
TIER_BANDS: dict[str, tuple[int, int, int]] = {
    'zu':   (200, 260, 230),
    'nu':   (260, 320, 290),
    'ru':   (320, 400, 360),
    'uu':   (400, 480, 440),
    'ou':   (480, 540, 510),
    'uber': (540, 600, 570),
}


@dataclass(frozen=True)
class Archetype:
    slug: str
    name: str
    flavor: str
    # Relative weights for (attack, defense, speed, lethality, grip, cunning).
    # Must sum to 1.0; we'll multiply by the tier's mid-point budget.
    weights: tuple[float, float, float, float, float, float]
    # Suggested attack/defense type families when the LLM doesn't override.
    typical_attack_types: tuple[str, ...] = ()
    typical_defense_types: tuple[str, ...] = ()
    # Example real bugs the LLM should think of when picking this archetype.
    exemplars: tuple[str, ...] = ()

    def base_stats(self, tier: str) -> dict[str, int]:
        """Apply this archetype's shape at the tier's midpoint budget."""
        _lo, _hi, mid = TIER_BANDS.get(tier, TIER_BANDS['uu'])
        a, d, s, l, g, c = self.weights
        # Multiply by 6 because mid is the SUM of six stats — each weight is
        # a share of that sum, but a single stat caps at 100, so 6*share gives
        # the per-stat value when the share is 1/6 of the budget.
        # Simpler: each stat = weight * budget. Then clamp to 1-100.
        def _bound(x: float) -> int:
            return max(1, min(100, int(round(x))))
        return {
            'attack':    _bound(a * mid),
            'defense':   _bound(d * mid),
            'speed':     _bound(s * mid),
            'lethality': _bound(l * mid),
            'grip':      _bound(g * mid),
            'cunning':   _bound(c * mid),
        }


# ── The 16 archetypes ──────────────────────────────────────────────────
# Each entry's weights sum to 1.0. Comments explain the combat identity.

ARCHETYPES: list[Archetype] = [
    # 1. Heavy beetle types: armor + sustained crushing power, low everything else.
    Archetype('heavy_tank', 'Heavy Tank',
              'Walls of chitin. Wins by attrition.',
              weights=(0.22, 0.26, 0.10, 0.13, 0.20, 0.09),
              typical_attack_types=('crushing',),
              typical_defense_types=('hard_shell', 'thick_hide'),
              exemplars=('Goliath beetle', 'Rhinoceros beetle', 'Hercules beetle')),

    # 2. Stag-beetle profile: grappling beast with armor, slow but irresistible.
    Archetype('grappler_beast', 'Grappler Beast',
              'Massive jaws + foot anchors. Wins clinches.',
              weights=(0.20, 0.20, 0.10, 0.13, 0.27, 0.10),
              typical_attack_types=('grappling', 'crushing'),
              typical_defense_types=('hard_shell',),
              exemplars=('Stag beetle', 'Diving beetle', 'Bessbug')),

    # 3. Mantid/raptorial striker: ambush, surgical strike, high lethality.
    Archetype('ambush_striker', 'Ambush Striker',
              'Patient, then explosive. Lethal first contact.',
              weights=(0.21, 0.13, 0.18, 0.18, 0.15, 0.15),
              typical_attack_types=('grappling', 'piercing'),
              typical_defense_types=('evasive',),
              exemplars=('Praying mantis', 'Mantispid', 'Ambush bug')),

    # 4. Salticid / wolf-spider class: ranged precision, high cunning.
    Archetype('precision_predator', 'Precision Predator',
              'Sees the gap, hits the gap.',
              weights=(0.17, 0.12, 0.20, 0.15, 0.18, 0.18),
              typical_attack_types=('piercing', 'venom'),
              typical_defense_types=('evasive', 'hairy_spiny'),
              exemplars=('Jumping spider', 'Wolf spider', 'Lynx spider')),

    # 5. Wasp / hornet class: venom-driven offense, semi-fragile.
    Archetype('venom_artist', 'Venom Artist',
              'Light frame, devastating sting.',
              weights=(0.16, 0.11, 0.18, 0.24, 0.13, 0.18),
              typical_attack_types=('venom',),
              typical_defense_types=('hairy_spiny', 'evasive'),
              exemplars=('Yellowjacket', 'Cicada killer', 'Velvet ant')),

    # 6. Chemical / spray defender: turns attacker's commitment into a wound.
    Archetype('chemical_sprayer', 'Chemical Sprayer',
              'Punishes commits with chemical retaliation.',
              weights=(0.13, 0.16, 0.13, 0.22, 0.13, 0.23),
              typical_attack_types=('chemical',),
              typical_defense_types=('toxic_skin', 'hard_shell'),
              exemplars=('Bombardier beetle', 'Stink bug', 'Whip scorpion')),

    # 7. Dragonfly / fly aerial: speed + cunning, fragile body.
    Archetype('aerial_speedster', 'Aerial Speedster',
              'Owns the air. Picks the angle.',
              weights=(0.16, 0.10, 0.27, 0.14, 0.11, 0.22),
              typical_attack_types=('piercing',),
              typical_defense_types=('evasive',),
              exemplars=('Dragonfly', 'Hover fly', 'Robber fly')),

    # 8. Ground sprinter: tiger beetles, cicindelids — chase + crush.
    Archetype('ground_sprinter', 'Ground Sprinter',
              'Runs prey down before it can react.',
              weights=(0.18, 0.13, 0.24, 0.16, 0.13, 0.16),
              typical_attack_types=('slashing', 'crushing'),
              typical_defense_types=('evasive',),
              exemplars=('Tiger beetle', 'Ground beetle', 'Velvet mite')),

    # 9. Trapper / web spinner: low speed, high grip and cunning.
    Archetype('web_trapper', 'Web Trapper',
              'Fight begins the moment the opponent touches the web.',
              weights=(0.10, 0.13, 0.08, 0.18, 0.28, 0.23),
              typical_attack_types=('grappling', 'venom'),
              typical_defense_types=('evasive', 'hairy_spiny'),
              exemplars=('Orb weaver', 'Funnel-web spider', 'Antlion larva')),

    # 10. Scorpion: armored grappler with venom finish.
    Archetype('armored_venomist', 'Armored Venomist',
              'Pinches first, stings last.',
              weights=(0.16, 0.18, 0.12, 0.22, 0.20, 0.12),
              typical_attack_types=('venom', 'grappling'),
              typical_defense_types=('hard_shell',),
              exemplars=('Scorpion', 'Pseudoscorpion', 'Whip scorpion')),

    # 11. Centipede / myriapod: speed + lethality on a long, segmented frame.
    Archetype('venom_runner', 'Venom Runner',
              'Many legs, fast venom, no patience.',
              weights=(0.16, 0.14, 0.20, 0.22, 0.16, 0.12),
              typical_attack_types=('venom',),
              typical_defense_types=('segmented_armor',),
              exemplars=('Centipede (Scolopendra)', 'House centipede')),

    # 12. Millipede / curl-defender: low offense, very high defense + chemistry.
    Archetype('curl_defender', 'Curl Defender',
              'Curls into an armored ring. Hardly attacks; barely dies.',
              weights=(0.07, 0.30, 0.08, 0.18, 0.12, 0.25),
              typical_attack_types=('chemical', 'neutral'),
              typical_defense_types=('segmented_armor', 'toxic_skin'),
              exemplars=('Millipede', 'Pill bug', 'Pill millipede')),

    # 13. Hairy/setal defender: tarantulas, dermestids — counter-irritant + bulk.
    Archetype('bristle_brawler', 'Bristle Brawler',
              'Touch it and regret it. Hairs everywhere.',
              weights=(0.18, 0.20, 0.13, 0.17, 0.18, 0.14),
              typical_attack_types=('piercing', 'grappling'),
              typical_defense_types=('hairy_spiny',),
              exemplars=('Tarantula', 'Carpet beetle larva', 'Caterpillar')),

    # 14. Camouflage / mimic: rare wins via cunning, low everything else.
    Archetype('cryptic_mimic', 'Cryptic Mimic',
              'Wins by not being seen.',
              weights=(0.13, 0.16, 0.13, 0.13, 0.13, 0.32),
              typical_attack_types=('neutral', 'piercing'),
              typical_defense_types=('evasive',),
              exemplars=('Walking stick', 'Leaf insect', 'Treehopper')),

    # 15. Swarmer / individually weak but tireless. Capped at NU/RU naturally.
    Archetype('swarmer', 'Swarmer',
              'One is harmless. Together, devastating.',
              weights=(0.14, 0.13, 0.18, 0.16, 0.15, 0.24),
              typical_attack_types=('piercing', 'venom'),
              typical_defense_types=('unarmored',),
              exemplars=('Ant', 'Termite', 'Honeybee worker', 'Aphid')),

    # 16. Aquatic / bio-electric specialist: rare exotic finisher.
    Archetype('exotic_finisher', 'Exotic Finisher',
              'A signature trait that breaks the matchup rules.',
              weights=(0.15, 0.13, 0.16, 0.23, 0.13, 0.20),
              typical_attack_types=('electric', 'sonic', 'chemical'),
              typical_defense_types=('bioluminescent', 'regenerative'),
              exemplars=('Bombardier beetle', 'Firefly', 'Cicada', 'Click beetle')),
]


_BY_SLUG = {a.slug: a for a in ARCHETYPES}


def get(slug: str) -> Optional[Archetype]:
    return _BY_SLUG.get(slug)


def all_archetypes() -> list[Archetype]:
    return list(ARCHETYPES)


def slugs() -> list[str]:
    return [a.slug for a in ARCHETYPES]


# ── LLM prompt block ──────────────────────────────────────────────────

def prompt_block() -> str:
    """Render the archetype table into the LLM stat-gen prompt.

    The model picks (archetype_slug, tier) and is allowed ±8 deviation
    per stat from the archetype's base. We surface every archetype with
    its weight signature so the model can match a bug to the right slug.
    """
    rows = []
    for a in ARCHETYPES:
        w = a.weights
        rows.append(
            f"- `{a.slug}` **{a.name}** — {a.flavor}\n"
            f"  weights atk/def/spd/lth/grp/cun = "
            f"{w[0]:.2f}/{w[1]:.2f}/{w[2]:.2f}/{w[3]:.2f}/{w[4]:.2f}/{w[5]:.2f}. "
            f"Exemplars: {', '.join(a.exemplars)}."
        )
    return "\n".join(rows)


def apply(archetype_slug: str, tier: str, deviations: Optional[dict] = None) -> dict[str, int]:
    """Compute final stats from archetype + tier + LLM per-stat deviation.

    `deviations` is a dict like {'attack': +5, 'speed': -3, ...}. Any
    deviation outside ±15 is clamped to ±15. After applying, totals are
    rebalanced to land inside the tier band.
    """
    arch = _BY_SLUG.get(archetype_slug)
    if arch is None:
        # Default to a balanced mid-archetype rather than throwing — the LLM
        # might invent a label and we still want to ship the bug.
        arch = _BY_SLUG.get('ground_sprinter')
        if arch is None:
            arch = ARCHETYPES[0]

    base = arch.base_stats(tier)
    stats = dict(base)

    if deviations:
        for k in stats:
            d = deviations.get(k)
            if d is None:
                continue
            try:
                d = int(d)
            except (TypeError, ValueError):
                continue
            d = max(-15, min(15, d))
            stats[k] = max(1, min(100, stats[k] + d))

    # Rebalance to the tier band — if total is outside, scale uniformly.
    lo, hi, _mid = TIER_BANDS.get(tier, TIER_BANDS['uu'])
    total = sum(stats.values())
    if total > 0 and (total < lo or total > hi):
        target = (lo + hi) // 2
        scale = target / total
        for k in stats:
            stats[k] = max(1, min(100, int(round(stats[k] * scale))))
        # After clamping individual stats to 1-100, the sum might still drift
        # a bit. One small pass of equal-distributed correction.
        drift = target - sum(stats.values())
        if drift:
            stat_keys = list(stats.keys())
            step = 1 if drift > 0 else -1
            i = 0
            while drift != 0 and i < 60:    # cap iterations
                key = stat_keys[i % 6]
                new_val = stats[key] + step
                if 1 <= new_val <= 100:
                    stats[key] = new_val
                    drift -= step
                i += 1

    return stats
