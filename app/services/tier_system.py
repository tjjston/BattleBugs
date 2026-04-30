"""
Tier System & LLM-Powered Stat Generation for BattleBugs Tournamanents
"""

from flask import current_app
from app import db
from app.models import Bug, Species, Battle
import json
from datetime import datetime, timedelta


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
        
        prompt = f"""You are an expert entomologist and game balance designer. Generate combat stats for this bug.

**Reference Dataset (for calibration):**
{context}

**Bug to Evaluate:**
- Common Name: {bug_info.get('common_name', 'Unknown')}
- Scientific Name: {bug_info.get('scientific_name', 'Unknown')}
- Size: {bug_info.get('size_mm', 'Unknown')}mm
- Characteristics: {bug_info.get('traits', [])}
- Species Info: {bug_info.get('species_info', 'N/A')}
{f"- Real-world facts: {'; '.join(bug_info['species_facts'])}" if bug_info.get('species_facts') else ''}

**Instructions:**
1. Compare this bug to the reference dataset to calibrate power level
2. Assign all six stats (1-100 scale):
   - Attack: Raw offensive power — mandible strength, strike force, body mass used offensively
   - Defense: Survivability — armor thickness, cuticle hardness, regenerative toughness
   - Speed: Agility and movement — reaction time, acceleration, evasion in the open
   - Lethality: How effectively the bug exploits type advantages — venom potency, precision strike, biological weaponry (e.g. explosive sprays, neurotoxin, acid)
   - Grip: Engagement control — clinging ability, grapple strength, limb hooks, suction (determines who controls range)
   - Cunning: Tactical adaptation — ability to mitigate type disadvantages through feints, terrain use, ambush timing, behavioral flexibility
3. Six-stat total budget by tier:
   - Legendary (Uber): 540-600 total
   - Strong (OU): 480-539 total
   - Average (UU): 400-479 total
   - Below Average (RU): 320-399 total
   - Weak (NU): 240-319 total
   - Very Weak (ZU): 0-239 total

4. Offensive Type: piercing | crushing | slashing | venom | chemical | grappling | sonic | electric | neutral
   - sonic: vibrational/stridulation attacks; bypasses rigid armor (crickets, some beetles)
   - electric: bioelectric discharge; conducts through shell and hide (very rare, exotic)
   - neutral: no dominant attack style; balanced fighter with no type advantage or weakness
5. Defensive Type: hard_shell | segmented_armor | evasive | hairy_spiny | toxic_skin | thick_hide | unarmored | regenerative | bioluminescent
   - unarmored: soft body with high metabolic resilience; weak to physical but somewhat resists chemical/venom
   - regenerative: rapid wound closure; resists sustained/gradual attacks but vulnerable to crushing
   - bioluminescent: light-flash confusion; disrupts aimed attacks (piercing, grappling) but useless vs chemical/sonic
6. Size Category: tiny (0-5mm) | small (6-20mm) | medium (21-50mm) | large (51-150mm) | massive (151mm+)
7. Assign a special ability based on the bug's real biological traits
8. Provide reasoning for the stat allocation

Respond in this EXACT JSON format (no markdown):
{{
  "attack": 1-100,
  "defense": 1-100,
  "speed": 1-100,
  "lethality": 1-100,
  "grip": 1-100,
  "cunning": 1-100,
  "attack_type": "piercing|crushing|slashing|venom|chemical|grappling|sonic|electric|neutral",
  "defense_type": "hard_shell|segmented_armor|evasive|hairy_spiny|toxic_skin|thick_hide|unarmored|regenerative|bioluminescent",
  "size_category": "tiny|small|medium|large|massive",
  "special_ability": "Ability name based on real traits",
  "reasoning": "Brief explanation of stat allocation",
  "tier_recommendation": "uber|ou|uu|ru|nu|zu",
  "confidence": 0.0-1.0
}}

BE REALISTIC: Most bugs should sit in the 360-440 total range (all six stats). Only truly exceptional predators reach 540+. Most bugs encountered in the midwest USA are common species — calibrate accordingly.
"""
        
        try:
            from app.services.llm_manager import LLMService
            llm = LLMService()
            current_app.logger.info(
                "STATS generating for %s / %s",
                bug_info.get('common_name'), bug_info.get('scientific_name'),
            )
            raw = llm.generate(prompt, task='stat_generation', max_tokens=4096, json_mode=True)
            if not raw:
                current_app.logger.warning("STATS LLM returned empty — task=stat_generation common=%s scientific=%s",
                    bug_info.get('common_name'), bug_info.get('scientific_name'))
                raise ValueError("LLM returned an empty response")

            # Robust extraction: try direct parse, then find {...} in prose
            import re as _re
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                _m = _re.search(r'\{.*\}', raw, _re.DOTALL)
                if _m:
                    result = json.loads(_m.group())
                else:
                    raise ValueError(f"No JSON in response: {raw[:200]}")

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
        }
        
        stats = self.generate_stats_with_llm(bug_info)
        
        bug.attack = max(0, min(100, int(stats['attack'])))
        bug.defense = max(0, min(100, int(stats['defense'])))
        bug.speed = max(0, min(100, int(stats['speed'])))
        bug.lethality = max(0, min(100, int(stats.get('lethality', 50))))
        bug.grip = max(0, min(100, int(stats.get('grip', 50))))
        bug.cunning = max(0, min(100, int(stats.get('cunning', 50))))
        bug.special_ability = stats.get('special_ability')
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
