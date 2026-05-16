"""
Tier System & LLM-Powered Stat Generation for BattleBugs Tournamanents
"""

from flask import current_app
from app import db
from app.models import Bug, Species, Battle
import json
from datetime import datetime, timedelta


def _parse_stats_json(raw: str):
    """Parse an LLM stat-block JSON response, tolerating truncation.

    Returns the parsed dict, or None if even the salvage attempts fail.
    Strategy: try strict json.loads, then locate the largest leading '{…}'
    span and parse that, then attempt to repair truncated JSON by closing
    any unmatched brackets/braces.
    """
    import re as _re

    # 1. Strict parse.
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        pass

    # 2. Locate the JSON object boundary.
    start = raw.find('{')
    if start < 0:
        return None
    candidate = raw[start:]

    # 3. Strict parse on the slice.
    try:
        return json.loads(candidate)
    except ValueError:
        pass

    # 4. Repair truncation: drop a trailing comma/partial token then close
    #    unmatched braces/brackets in reverse open order.
    text = candidate.rstrip()
    text = _re.sub(r'[,\s]+$', '', text)
    # Drop a trailing partial key/value like `"grip": 97` if the next token never came
    # by trimming back to the last balanced position.
    in_string = False
    escape = False
    stack = []
    last_balanced = -1
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in '{[':
            stack.append(ch)
        elif ch in '}]':
            if stack:
                stack.pop()
            if not stack:
                last_balanced = i

    if last_balanced >= 0:
        try:
            return json.loads(text[:last_balanced + 1])
        except ValueError:
            pass

    # 5. Last-ditch repair: close every open container.
    repaired = text
    if in_string:
        repaired += '"'
    # If the last meaningful char is a colon or comma, the value is missing — drop it.
    repaired = _re.sub(r'[,:]\s*$', '', repaired)
    closers = {'{': '}', '[': ']'}
    for opener in reversed(stack):
        repaired += closers[opener]
    try:
        return json.loads(repaired)
    except ValueError:
        return None


def _fallback_stats(bug_info: dict) -> dict:
    """Deterministic varied stats when LLM is unavailable.

    Seeded from the species name so the same bug always gets the same fallback
    stats rather than boring all-50s.
    """
    import hashlib
    import random as _r

    name = (bug_info.get('scientific_name') or bug_info.get('common_name') or 'Unknown')
    seed = int(hashlib.md5(name.encode()).hexdigest()[:8], 16)
    rng = _r.Random(seed)

    _ATTACK_TYPES = ['piercing', 'crushing', 'slashing', 'venom', 'chemical', 'grappling', 'neutral']
    _DEFENSE_TYPES = ['hard_shell', 'segmented_armor', 'evasive', 'hairy_spiny', 'thick_hide', 'unarmored']

    # Budget 300–420 split unevenly across 6 stats
    raw = [rng.randint(25, 75) for _ in range(6)]
    total_budget = rng.randint(300, 420)
    scale = total_budget / sum(raw)
    vals = [max(1, min(100, round(v * scale))) for v in raw]

    return {
        'attack': vals[0], 'defense': vals[1], 'speed': vals[2],
        'lethality': vals[3], 'grip': vals[4], 'cunning': vals[5],
        'attack_type': rng.choice(_ATTACK_TYPES),
        'defense_type': rng.choice(_DEFENSE_TYPES),
        'special_ability': 'Survival Instinct',
        'reasoning': 'Auto-generated (LLM unavailable); an admin can recalculate.',
        'tier_recommendation': 'nu',
        'confidence': 0.3,
    }


# Tourney Tiers
TIER_DEFINITIONS = {
    'uber': {
        'name': 'Legendary',
        'description': 'Legendary bugs - the absolute strongest',
        'min_power': 540,  # sum of all 6 stats (max 600)
        'icon': '👑',
        'color': '#FFD700'
    },
    'ou': {
        'name': 'A Tier',
        'description': 'Top tier competitors',
        'min_power': 480,
        'max_power': 539,
        'icon': '⭐',
        'color': '#C0C0C0'
    },
    'uu': {
        'name': 'B Tier',
        'description': 'Strong but not overpowered',
        'min_power': 400,
        'max_power': 479,
        'icon': '🥈',
        'color': '#CD7F32'
    },
    'ru': {
        'name': 'C Tier',
        'description': 'Middle of the pack',
        'min_power': 320,
        'max_power': 399,
        'icon': '🥉',
        'color': '#8B7355'
    },
    'nu': {
        'name': 'D Tier',
        'description': 'Underdogs with heart',
        'min_power': 240,
        'max_power': 319,
        'icon': '💪',
        'color': '#A9A9A9'
    },
    'zu': {
        'name': 'Little Cup',
        'description': 'The brave beginners',
        'min_power': 0,
        'max_power': 239,
        'icon': '🌱',
        'color': '#90EE90'
    }
}


# Consolidated TierSystem defined once below

class TierSystem:
    """Manage bug tiers for balanced matchmaking"""
    
    @staticmethod
    def calculate_power_rating(bug):
        """Calculate overall power rating across all 6 combat stats"""
        return (
            (bug.attack or 0) + (bug.defense or 0) + (bug.speed or 0)
            + (getattr(bug, 'lethality', 50) or 50)
            + (getattr(bug, 'grip', 50) or 50)
            + (getattr(bug, 'cunning', 50) or 50)
        )
    
    @staticmethod
    def assign_tier(bug):
        """
        Assign tier based on power rating and performance
        
        Args:
            bug: Bug object
            
        Returns:
            str: Tier code ('uber', 'ou', 'uu', etc.)
        """
        power = TierSystem.calculate_power_rating(bug)
        
        # Base tier on power rating
        for tier_code, tier_info in TIER_DEFINITIONS.items():
            min_power = tier_info.get('min_power', 0)
            max_power = tier_info.get('max_power', 999)
            
            if min_power <= power <= max_power:
                return tier_code
        
        # Fallback
        return 'zu'
    
    @staticmethod
    def can_battle(bug1, bug2, allow_tier_difference=None, tournament_tier_restriction=None):
        """
        Check if two bugs can battle based on tiers
        
        Args:
            bug1, bug2: Bug objects
            allow_tier_difference: How many tiers apart bugs can be (None = no restriction)
            tournament_tier_restriction: Specific tier for tournament battles (e.g., 'ou')
            
        Returns:
            dict with can_battle (bool) and reason (str)
        """
        # For tournament-specific battles, check tier restriction
        if tournament_tier_restriction:
            tier1 = bug1.tier or TierSystem.assign_tier(bug1)
            tier2 = bug2.tier or TierSystem.assign_tier(bug2)
            
            if tier1 != tournament_tier_restriction or tier2 != tournament_tier_restriction:
                return {
                    'can_battle': False,
                    'reason': f'Tournament restricted to {TIER_DEFINITIONS[tournament_tier_restriction]["name"]} tier',
                    'tier_difference': None
                }
            else:
                return {
                    'can_battle': True,
                    'reason': 'Tiers compatible for tournament',
                    'tier_difference': 0
                }
        
        if allow_tier_difference is not None:
            tier1 = bug1.tier or TierSystem.assign_tier(bug1)
            tier2 = bug2.tier or TierSystem.assign_tier(bug2)
            
            tier_order = list(TIER_DEFINITIONS.keys())
            
            try:
                tier1_idx = tier_order.index(tier1)
                tier2_idx = tier_order.index(tier2)
                
                difference = abs(tier1_idx - tier2_idx)
                
                if difference <= allow_tier_difference:
                    return {
                        'can_battle': True,
                        'reason': 'Tiers compatible',
                        'tier_difference': difference
                    }
                else:
                    return {
                        'can_battle': False,
                        'reason': f'Tier mismatch: {TIER_DEFINITIONS[tier1]["name"]} vs {TIER_DEFINITIONS[tier2]["name"]}',
                        'tier_difference': difference
                    }
            except ValueError:
                return {
                    'can_battle': True,
                    'reason': 'Invalid tier, allowing battle',
                    'tier_difference': 0
                }
        
        return {
            'can_battle': True,
            'reason': 'All battles allowed',
            'tier_difference': None
        }

class LLMStatGenerator:
    """Generate bug stats using LLM with contextual understanding"""

    def __init__(self):
        self.reference_dataset = self._load_reference_data()
    
    def _load_reference_data(self):
        """
        Load reference dataset for stat generation
        This provides context about relative bug power levels
        """
        return {
            'legendary_bugs': [
                {
                    'name': 'Black Widow Spider',
                    'scientific': 'Latrodectus mactans',
                    'size_mm': 12,
                    'traits': ['highly venomous', 'neurotoxic', 'ambush predator'],
                    'attack': 96, 'defense': 75, 'speed': 88,
                    'reasoning': 'Medically significant neurotoxic venom; apex ambush predator among spiders'
                },
                {
                    'name': 'Goliath Beetle',
                    'scientific': 'Goliathus goliatus',
                    'size_mm': 110,
                    'traits': ['massive', 'armored', 'strong pincers'],
                    'attack': 93, 'defense': 82, 'speed': 44,
                    'reasoning': 'One of the heaviest insects - raw power compensates for slow speed'
                },
                {
                    'name': 'Bullet Ant',
                    'scientific': 'Paraponera clavata',
                    'size_mm': 25,
                    'traits': ['most painful sting', 'aggressive', 'strong mandibles'],
                    'attack': 99, 'defense': 34, 'speed': 78,
                    'reasoning': 'Legendary venom - highest pain index of any insect'
                },
                {
                    'name': 'Brown Recluse Spider',
                    'scientific': 'Loxosceles reclusa',
                    'size_mm': 10,
                    'traits': ['venomous', 'reclusive', 'web-building'],
                    'attack': 98, 'defense': 65, 'speed': 88,
                    'reasoning': 'Fastest strike in nature - can break aquarium glass'
                },

                {
                    'name': 'Japanese Giant Hornet',
                    'scientific': 'Vespa mandarinia',
                    'size_mm': 50,
                    'traits': ['venomous', 'aggressive', 'fast flier'],
                    'attack': 9, 'defense': 6, 'speed': 8,
                    'reasoning': 'Largest hornet species - highly venomous and aggressive'
                },
                {
                    'name': 'Tarantula Hawk Wasp',
                    'scientific': 'Pepsis grossa',
                    'size_mm': 50,
                    'traits': ['venomous', 'aggressive', 'fast flier'],
                    'attack': 85, 'defense': 40, 'speed': 90,
                    'reasoning': 'Powerful sting used to paralyze tarantulas; very fast and agile'
                }
            ],
            'strong_bugs': [
                {
                    'name': 'Green Shield Bug',
                    'scientific': 'Palomena prasina',
                    'size_mm': 45,
                    'traits': ['venomous', 'aggressive', 'fast flier'],
                    'attack': 81, 'defense': 50, 'speed': 82,
                    'reasoning': 'Armored and fast - packs a strong strike for its class'
                },
                {
                    'name': 'Bombadeer Beetle',
                    'scientific': 'Brachinus spp.',
                    'size_mm': 12,
                    'traits': ['chemical defense', 'fast', 'nocturnal'],
                    'attack': 62, 'defense': 56, 'speed': 71,
                    'reasoning': 'Uses chemical spray to deter predators, quick and elusive'
                },
                {
                    'name': 'Hercules Beetle',
                    'scientific': 'Dynastes hercules',
                    'size_mm': 178,
                    'traits': ['horns', 'armored', 'strong', 'can fly'],
                    'attack': 88, 'defense': 85, 'speed': 55,
                    'reasoning': 'Proportionally strongest - can lift 850x body weight'
                },

            ],
            'average_bugs': [
                {
                    'name': 'Carpenter Ant',
                    'scientific': 'Camponotus pennsylvanicus',
                    'size_mm': 13,
                    'traits': ['mandibles', 'colonial', 'persistent'],
                    'attack': 43, 'defense': 51, 'speed': 66,
                    'reasoning': 'Average combat capability - strength in numbers'
                },
                {
                    'name': 'House Cricket',
                    'scientific': 'Acheta domesticus',
                    'size_mm': 20,
                    'traits': ['jumper', 'agile', 'weak mandibles'],
                    'attack': 31, 'defense': 37, 'speed': 84,
                    'reasoning': 'Evasion over combat - built for escape'
                }
            ],
            'weak_bugs': [
                {
                    'name': 'Fruit Fly',
                    'scientific': 'Drosophila melanogaster',
                    'size_mm': 3,
                    'traits': ['tiny', 'fast', 'fragile'],
                    'attack': 4, 'defense': 9, 'speed': 79,
                    'reasoning': 'Smallest combat unit - speed is only advantage'
                },
                {
                    'name': 'Aphid',
                    'scientific': 'Aphidoidea spp.',
                    'size_mm': 2,
                    'traits': ['tiny', 'plant feeder', 'fragile'],
                    'attack': 6, 'defense': 12, 'speed': 65,
                    'reasoning': 'Tiny and fragile - relies on rapid reproduction for survival'
                },
                {
                    'name': 'Caddisfly Larva',
                    'scientific': 'Trichoptera spp.',
                    'size_mm': 10,
                    'traits': ['aquatic larvae', 'weak mandibles', 'slow'],
                    'attack': 7, 'defense': 14, 'speed': 58,
                    'reasoning': 'Aquatic larvae are vulnerable - limited combat ability'
                }
            ]
        }
    
    def generate_stats_with_llm(self, bug_info):
        """
        Generate stats using LLM with context from reference dataset
        
        Args:
            bug_info: dict with:
                - scientific_name
                - common_name
                - size_mm
                - traits (list)
                - species_characteristics
                
        Returns:
            dict with attack, defense, speed, reasoning, special_ability, tier
        """
        context = self._build_reference_context()

        baseline = bug_info.get('species_baseline')
        baseline_block = ""
        if baseline and baseline.get('attack') is not None:
            baseline_block = f"""
**SPECIES BASELINE (from {baseline['sample_size']} previously-rated {bug_info.get('common_name') or bug_info.get('scientific_name')} bugs):**
- attack: {baseline.get('attack')}  defense: {baseline.get('defense')}  speed: {baseline.get('speed')}
- lethality: {baseline.get('lethality')}  grip: {baseline.get('grip')}  cunning: {baseline.get('cunning')}
- attack_type: {baseline.get('attack_type')}  defense_type: {baseline.get('defense_type')}
- size_category: {baseline.get('size_category')}  tier: {baseline.get('tier')}
- typical special_ability: {baseline.get('special_ability')}

ANCHORING RULE — this is the most important instruction:
The same species must produce roughly the same stats. Stay within ±8 points of every baseline stat AND keep the same attack_type / defense_type / size_category as the baseline, UNLESS the visual observations below give a concrete biological reason to deviate (e.g. unusually large specimen, missing limb, distinctive coloration, damaged wings). When you do deviate, name the visual cue explicitly in the per-stat reasoning. Do not introduce variance for its own sake.
"""

        visual = bug_info.get('visual_observations') or {}
        visual_block = ""
        if visual:
            visual_lines = []
            for k, v in visual.items():
                if v is None or v == "":
                    continue
                visual_lines.append(f"- {k}: {v}")
            if visual_lines:
                visual_block = "\n**Visual observations from THIS specimen's photo (the only legitimate reason to deviate from the baseline):**\n" + "\n".join(visual_lines) + "\n"

        prompt = f"""You are a senior entomologist and competitive game-balance designer. Your job is to produce combat stats for a real-world bug AND a thorough, biology-grounded explanation a player can read on a "Why these stats?" popup.

**Reference Dataset (for power-level calibration):**
{context}
{baseline_block}{visual_block}
**Bug to Evaluate:**
- Common Name: {bug_info.get('common_name', 'Unknown')}
- Scientific Name: {bug_info.get('scientific_name', 'Unknown')}
- Size: {bug_info.get('size_mm', 'Unknown')}mm
- Observed traits: {bug_info.get('traits', [])}
- Species Info: {bug_info.get('species_info', 'N/A')}
{f"- Real-world facts: {'; '.join(bug_info['species_facts'])}" if bug_info.get('species_facts') else ''}

**Stat definitions (each 1-100):**
- attack: raw offensive power — mandible/chelicerae strength, strike force, body mass used offensively
- defense: survivability — cuticle hardness, armor thickness, regenerative toughness
- speed: agility — reaction time, acceleration, evasion in the open
- lethality: how decisively it exploits a type advantage — venom potency, precision strike, biological weaponry (sprays, neurotoxin, acid)
- grip: engagement control — clinging, grapple strength, hooks, suction (decides who controls range)
- cunning: tactical adaptation — feints, terrain use, ambush timing, behavioral flexibility

**Total-stat budget by tier (sum of all six):**
- uber (legendary): 540-600
- ou (strong): 480-539
- uu (average): 400-479
- ru (below average): 320-399
- nu (weak): 240-319
- zu (very weak): 0-239

**Categorical fields:**
- attack_type: piercing | crushing | slashing | venom | chemical | grappling | sonic | electric | neutral
  • sonic: vibrational/stridulation; bypasses rigid armor
  • electric: bioelectric discharge; conducts through shell and hide (rare)
  • neutral: balanced fighter with no type advantage or weakness
- defense_type: hard_shell | segmented_armor | evasive | hairy_spiny | toxic_skin | thick_hide | unarmored | regenerative | bioluminescent
  • unarmored: soft body, high metabolic resilience; weak to physical, somewhat resists chemical/venom
  • regenerative: rapid wound closure; resists sustained attacks, vulnerable to crushing
  • bioluminescent: light-flash confusion; disrupts piercing/grappling, useless vs chemical/sonic
- size_category: tiny (0-5mm) | small (6-20mm) | medium (21-50mm) | large (51-150mm) | massive (151mm+)

**Process — follow in order:**
1. If a SPECIES BASELINE is provided above, START from those numbers and types. Otherwise identify the closest 1-2 reference bugs from the dataset and calibrate against them.
2. Read the visual observations. If a specific visual cue justifies adjusting the baseline (e.g. "specimen unusually large", "missing leg", "intact, vibrant"), apply a deliberate, named adjustment within ±8 points. If nothing in the photo warrants change, keep the baseline values.
3. Pick attack_type, defense_type, size_category, and a real-trait-based special_ability — match the baseline unless visuals demand otherwise.
4. Assign each of the six stats with a one-sentence biological justification per stat (cite anatomy, venom/chemistry, behavior, or ecology — no vague filler). For any stat that deviates from a provided baseline, the justification MUST reference the specific visual cue.
5. Pick a tier whose budget matches the sum of your six stats. If they disagree, adjust the stats, not the budget.
6. Write a 2-4 sentence summary tying it all together — what kind of fighter is this, where it shines, and where it loses.

**Calibration reminder:** Most North American garden bugs fall in the 360-440 total range. Only truly exceptional predators (large mantids, scorpions, hornets, large centipedes) reach 540+. Common pollinators, beetles, and small spiders should sit in uu/ru.

Respond with valid JSON only — no prose, no markdown fences — in EXACTLY this shape:
{{
  "attack": 1-100,
  "defense": 1-100,
  "speed": 1-100,
  "lethality": 1-100,
  "grip": 1-100,
  "cunning": 1-100,
  "attack_type": "...",
  "defense_type": "...",
  "size_category": "...",
  "special_ability": "Concrete ability name grounded in real biology",
  "tier_recommendation": "uber|ou|uu|ru|nu|zu",
  "confidence": 0.0-1.0,
  "reasoning": {{
    "summary": "2-4 sentence overall read of the fighter",
    "calibration": "Which reference bug(s) anchored the rating and why",
    "key_factors": ["3-6 concise biological factors that drove the numbers"],
    "per_stat": {{
      "attack":    "one-sentence reason citing anatomy/behavior",
      "defense":   "one-sentence reason",
      "speed":     "one-sentence reason",
      "lethality": "one-sentence reason",
      "grip":      "one-sentence reason",
      "cunning":   "one-sentence reason"
    }},
    "matchups": {{
      "strong_against": "the kind of opponent this bug beats and why",
      "weak_against":   "the kind of opponent that beats this bug and why"
    }},
    "baseline_deviation": "If a species baseline was provided, briefly state how this specimen differs from it and which visual cue justified the change. If no baseline existed, write 'first of species — sets the baseline'. If you stayed exactly on baseline, write 'matches species baseline'."
  }}
}}
"""
        
        try:
            from app.services.llm_manager import LLMService
            llm = LLMService()
            current_app.logger.info(
                "STATS generating for %s / %s",
                bug_info.get('common_name'), bug_info.get('scientific_name'),
            )
            raw = llm.generate(prompt, task='stat_generation', max_tokens=6144, json_mode=True)
            if not raw:
                current_app.logger.warning("STATS LLM returned empty — task=stat_generation common=%s scientific=%s",
                    bug_info.get('common_name'), bug_info.get('scientific_name'))
                raise ValueError("LLM returned an empty response")

            result = _parse_stats_json(raw)
            if result is None:
                raise ValueError(f"Could not extract JSON from response: {raw[:300]}")

            # Validate
            if not all(k in result for k in ['attack', 'defense', 'speed']):
                raise ValueError("Missing required stat fields")

            # Clamp all stats to valid range
            for stat in ('attack', 'defense', 'speed', 'lethality', 'grip', 'cunning'):
                result[stat] = max(1, min(100, result.get(stat, 50)))

            return result

        except Exception as e:
            current_app.logger.warning(
                "STATS generation failed (%s: %s) — using fallback for %s",
                type(e).__name__, e, bug_info.get('common_name'),
            )
            return _fallback_stats(bug_info)
    
    def _build_reference_context(self):
        """Build formatted reference context for LLM"""
        context_parts = []
        
        for category, bugs in self.reference_dataset.items():
            context_parts.append(f"\n**{category.replace('_', ' ').title()}:**")
            for bug in bugs:
                if not isinstance(bug, dict) or not bug:
                    # Skip invalid or placeholder entries
                    continue
                name = bug.get('name', 'Unknown')
                scientific = bug.get('scientific', 'Unknown')
                size_mm = bug.get('size_mm', 'Unknown')
                attack = bug.get('attack')
                defense = bug.get('defense')
                speed = bug.get('speed')
                # If core stats are missing, skip this entry
                if attack is None or defense is None or speed is None:
                    continue
                total = (attack or 0) + (defense or 0) + (speed or 0)
                reasoning = bug.get('reasoning', 'No reasoning provided')
                context_parts.append(
                    f"- {name} ({scientific}): "
                    f"Size {size_mm}mm, "
                    f"ATK:{attack} DEF:{defense} SPD:{speed} "
                    f"(Total: {total}) "
                    f"- {reasoning}"
                )
        
        return '\n'.join(context_parts)
    
    def _get_species_baseline(self, bug):
        """Aggregate stats from other already-statted bugs of the same species.

        Returns a dict with median per-stat values + modal categorical fields,
        or None if there are no peers. Used to keep the LLM's output consistent
        across submissions of the same species.
        """
        from collections import Counter

        peers = Bug.query.filter(
            Bug.id != bug.id,
            Bug.stats_generated.is_(True),
        )
        if bug.species_id:
            peers = peers.filter(Bug.species_id == bug.species_id)
        elif bug.scientific_name:
            peers = peers.filter(Bug.scientific_name == bug.scientific_name)
        else:
            return None
        peers = peers.limit(25).all()
        if not peers:
            return None

        def _median(values):
            vs = sorted(v for v in values if v is not None)
            if not vs:
                return None
            mid = len(vs) // 2
            if len(vs) % 2 == 1:
                return vs[mid]
            return int(round((vs[mid - 1] + vs[mid]) / 2))

        def _mode(values):
            vs = [v for v in values if v]
            if not vs:
                return None
            return Counter(vs).most_common(1)[0][0]

        return {
            'sample_size': len(peers),
            'attack':    _median(p.attack for p in peers),
            'defense':   _median(p.defense for p in peers),
            'speed':     _median(p.speed for p in peers),
            'lethality': _median(p.lethality for p in peers),
            'grip':      _median(p.grip for p in peers),
            'cunning':   _median(p.cunning for p in peers),
            'attack_type':    _mode(p.attack_type for p in peers),
            'defense_type':   _mode(p.defense_type for p in peers),
            'size_category':  _mode(p.size_class for p in peers),
            'special_ability': _mode(p.special_ability for p in peers),
            'tier':           _mode(p.tier for p in peers),
        }

    def _extract_visual_observations(self, bug):
        """Pull LLM-vision observations + physical condition from the bug record.

        These are the *photo-specific* cues that should drive variance away from
        the species baseline (e.g. an unusually large specimen, a missing limb).
        """
        fields = {
            'analysis':         bug.visual_lore_analysis,
            'items':            bug.visual_lore_items,
            'environment':      bug.visual_lore_environment,
            'posture':          bug.visual_lore_posture,
            'unique_features':  bug.visual_lore_unique_features,
            'condition':        bug.condition,
            'condition_notes':  bug.condition_notes,
            'vision_identified_species': bug.vision_identified_species,
            'vision_quality_score': bug.vision_quality_score,
        }
        return {k: v for k, v in fields.items() if v}

    def regenerate_stats_for_bug(self, bug):
        """
        Regenerate stats for an existing bug using LLM

        Args:
            bug: Bug object

        Returns:
            Updated bug with new stats
        """
        facts = []
        if bug.species_info and bug.species_info.interesting_facts:
            try:
                import json as _j
                facts = _j.loads(bug.species_info.interesting_facts)[:3]
            except Exception:
                pass
        bug_info = {
            'scientific_name': bug.scientific_name,
            'common_name': bug.common_name,
            'size_mm': bug.species_info.average_size_mm if bug.species_info else None,
            'traits': self._extract_traits(bug),
            'species_info': bug.species_info.to_dict() if bug.species_info else None,
            'species_facts': facts,
            'species_baseline': self._get_species_baseline(bug),
            'visual_observations': self._extract_visual_observations(bug),
        }

        stats = self.generate_stats_with_llm(bug_info)
        
        bug.attack = max(0, min(100, int(stats['attack'])))
        bug.defense = max(0, min(100, int(stats['defense'])))
        bug.speed = max(0, min(100, int(stats['speed'])))
        bug.lethality = max(0, min(100, int(stats.get('lethality', 50))))
        bug.grip = max(0, min(100, int(stats.get('grip', 50))))
        bug.cunning = max(0, min(100, int(stats.get('cunning', 50))))
        bug.special_ability = stats.get('special_ability')
        # Resolve the LLM-coined ability name to a canonical catalog slug so
        # the battle engine can apply a balanced combat modifier.
        try:
            from app.services import ability_catalog as _ac
            resolved = _ac.resolve(
                bug.special_ability,
                attack_type=stats.get('attack_type'),
                defense_type=stats.get('defense_type'),
            )
            if resolved:
                bug.ability_slug = resolved.slug
        except Exception:
            pass
        # Capture combat characteristic suggestions from the LLM
        if 'attack_type' in stats:
            bug.attack_type = stats.get('attack_type')
        if 'defense_type' in stats:
            bug.defense_type = stats.get('defense_type')
        # Normalize size naming (accept 'giant' from older prompts)
        raw_size = stats.get('size_category') or stats.get('size')
        if raw_size:
            sc = raw_size.lower()
            if sc == 'giant':
                sc = 'massive'
            bug.size_class = sc
        bug.stats_generation_method = 'llm_contextual'
        bug.stats_generated = True

        reasoning = stats.get('reasoning')
        if reasoning is not None:
            try:
                bug.stats_reasoning = json.dumps(reasoning, ensure_ascii=False)
            except (TypeError, ValueError):
                bug.stats_reasoning = json.dumps({'summary': str(reasoning)}, ensure_ascii=False)
        
        # Assign tier
        bug.tier = TierSystem.assign_tier(bug)
        
        db.session.commit()
        
        return bug
    
    def _extract_traits(self, bug):
        """Extract traits from bug and species info"""
        traits = []
        
        if bug.species_info:
            species = bug.species_info
            if species.has_venom:
                traits.append('venomous')
            if species.has_pincers:
                traits.append('pincers')
            if species.has_stinger:
                traits.append('stinger')
            if species.can_fly:
                traits.append('flight')
            if species.has_armor:
                traits.append('armored')
            
            if species.average_size_mm:
                if species.average_size_mm > 50:
                    traits.append('large')
                elif species.average_size_mm < 10:
                    traits.append('tiny')
        
        return traits


def assign_tier_and_generate_stats(bug, use_llm=True):
    """
    Helper function to generate stats and assign tier
    
    Args:
        bug: Bug object (with species_info populated)
        use_llm: Use LLM for stat generation (vs simple algorithm)
        
    Returns:
        Updated bug with stats and tier
    """
    if use_llm:
        generator = LLMStatGenerator()
        bug = generator.regenerate_stats_for_bug(bug)
    else:
        from app.services.taxonomy import StatsGenerator
        generator = StatsGenerator()
        stats = generator.generate_stats(bug)
        bug.attack = stats['attack']
        bug.defense = stats['defense']
        bug.speed = stats['speed']
        bug.lethality = stats.get('lethality', 50)
        bug.grip = stats.get('grip', 50)
        bug.cunning = stats.get('cunning', 50)
        bug.special_ability = stats.get('special_ability')
    
    # Always assign tier after stats are set
    bug.tier = TierSystem.assign_tier(bug)
    bug.stats_generated = True
    
    db.session.commit()
    
    return bug
