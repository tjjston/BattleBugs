"""
Tier System & LLM-Powered Stat Generation for BattleBugs Tournamanents
"""

from anthropic import Anthropic
from flask import current_app
from app import db
from app.models import Bug, Species, Battle
import json
from datetime import datetime, timedelta

# Tourney Tiers
TIER_DEFINITIONS = {
    'uber': {
        'name': 'Legendary',
        'description': 'Legendary bugs - the absolute strongest',
        'min_power': 27,  # Attack + Defense + Speed >= 27
        'icon': '👑',
        'color': '#FFD700'
    },
    'ou': {
        'name': 'A Tier',
        'description': 'Top tier competitors',
        'min_power': 24,
        'max_power': 26,
        'icon': '⭐',
        'color': '#C0C0C0'
    },
    'uu': {
        'name': 'B Tier', 
        'description': 'Strong but not overpowered',
        'min_power': 20,
        'max_power': 23,
        'icon': '🥈',
        'color': '#CD7F32'
    },
    'ru': {
        'name': 'C Tier',
        'description': 'Middle of the pack',
        'min_power': 16,
        'max_power': 19,
        'icon': '🥉',
        'color': '#8B7355'
    },
    'nu': {
        'name': 'D Tier',
        'description': 'Underdogs with heart',
        'min_power': 12,
        'max_power': 15,
        'icon': '💪',
        'color': '#A9A9A9'
    },
    'zu': {
        'name': 'Little Cup',
        'description': 'The brave beginners',
        'min_power': 0,
        'max_power': 11,
        'icon': '🌱',
        'color': '#90EE90'
    }
}


class TierSystem:
    """Manage bug tiers for balanced matchmaking"""
    
    @staticmethod
    def calculate_power_rating(bug):
        """Calculate overall power rating"""
        return bug.attack + bug.defense + bug.speed
    
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

// ... existing code ...

class TierSystem:
    """Manage bug tiers for balanced matchmaking"""
    
    @staticmethod
    def calculate_power_rating(bug):
        """Calculate overall power rating"""
        return bug.attack + bug.defense + bug.speed
    
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
        self.client = None
        self.reference_dataset = self._load_reference_data()
    
    def _get_client(self):
        if not self.client:
            api_key = current_app.config.get('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            self.client = Anthropic(api_key=api_key)
        return self.client
    
    def _load_reference_data(self):
        """
        Load reference dataset for stat generation
        This provides context about relative bug power levels
        """
        return {
            'legendary_bugs': [
                {
                    'name': 'Goliath Beetle',
                    'scientific': 'Goliathus goliatus',
                    'size_mm': 110,
                    'traits': ['massive', 'armored', 'strong pincers'],
                    'attack': 9, 'defense': 8, 'speed': 4,
                    'reasoning': 'One of the heaviest insects - raw power compensates for slow speed'
                },
                {
                    'name': 'Bullet Ant',
                    'scientific': 'Paraponera clavata',
                    'size_mm': 25,
                    'traits': ['most painful sting', 'aggressive', 'strong mandibles'],
                    'attack': 10, 'defense': 4, 'speed': 7,
                    'reasoning': 'Legendary venom - highest pain index of any insect'
                },
                {
                    'name': 'Mantis Shrimp',
                    'scientific': 'Odontodactylus scyllarus',
                    'size_mm': 180,
                    'traits': ['fastest strike', 'armored', 'visual predator'],
                    'attack': 10, 'defense': 7, 'speed': 10,
                    'reasoning': 'Fastest strike in nature - can break aquarium glass'
                }
            ],
            'strong_bugs': [
                {
                    'name': 'Japanese Hornet',
                    'scientific': 'Vespa mandarinia',
                    'size_mm': 45,
                    'traits': ['venomous', 'aggressive', 'fast flier'],
                    'attack': 8, 'defense': 5, 'speed': 8,
                    'reasoning': 'Apex predator of insects - hunts in groups'
                },
                {
                    'name': 'Hercules Beetle',
                    'scientific': 'Dynastes hercules',
                    'size_mm': 178,
                    'traits': ['horns', 'armored', 'strong', 'can fly'],
                    'attack': 8, 'defense': 8, 'speed': 5,
                    'reasoning': 'Proportionally strongest - can lift 850x body weight'
                }
            ],
            'average_bugs': [
                {
                    'name': 'Carpenter Ant',
                    'scientific': 'Camponotus pennsylvanicus',
                    'size_mm': 13,
                    'traits': ['mandibles', 'colonial', 'persistent'],
                    'attack': 5, 'defense': 5, 'speed': 6,
                    'reasoning': 'Average combat capability - strength in numbers'
                },
                {
                    'name': 'House Cricket',
                    'scientific': 'Acheta domesticus',
                    'size_mm': 20,
                    'traits': ['jumper', 'agile', 'weak mandibles'],
                    'attack': 3, 'defense': 3, 'speed': 8,
                    'reasoning': 'Evasion over combat - built for escape'
                }
            ],
            'weak_bugs': [
                {
                    'name': 'Fruit Fly',
                    'scientific': 'Drosophila melanogaster',
                    'size_mm': 3,
                    'traits': ['tiny', 'fast', 'fragile'],
                    'attack': 1, 'defense': 1, 'speed': 7,
                    'reasoning': 'Smallest combat unit - speed is only advantage'
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
        client = self._get_client()
        
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

**Instructions:**
1. Compare this bug to the reference dataset to calibrate power level
2. Consider: size, venom, armor, speed, predatory behavior, defensive capabilities
3. Assign stats (1-10 scale):
   - Attack: Offensive capability (venom, pincers, mandibles, strike power)
   - Defense: Survivability (armor, size, evasion, hardiness)
   - Speed: Agility and reaction time
4. Total stats should be balanced based on tier:
   - Legendary (Uber): 27-30 total
   - Strong (OU): 24-26 total
   - Average (UU): 20-23 total
   - Weak (RU): 16-19 total
   - Very Weak (NU/ZU): 12-15 total
5. Assign a special ability based on the bug's real characteristics
6. Provide reasoning for your stat allocation

Respond in this EXACT JSON format (no markdown):
{{
  "attack": 1-10,
  "defense": 1-10,
  "speed": 1-10,
  "special_ability": "Ability name based on real traits",
  "reasoning": "Brief explanation of stat allocation",
  "tier_recommendation": "uber/ou/uu/ru/nu/zu",
  "confidence": 0.0-1.0
}}

BE REALISTIC: Most bugs should be in the 18-22 total stat range. Only truly legendary bugs get 27+.
"""
        
        try:
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
            )
            
            response_text = message.content[0].text
            
            # Strip markdown if present
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            
            result = json.loads(response_text)
            
            # Validate
            if not all(k in result for k in ['attack', 'defense', 'speed']):
                raise ValueError("Missing required stat fields")
            
            # Ensure stats are in range
            result['attack'] = max(1, min(10, result['attack']))
            result['defense'] = max(1, min(10, result['defense']))
            result['speed'] = max(1, min(10, result['speed']))
            
            return result
            
        except Exception as e:
            print(f"LLM stat generation error: {e}")
            # Fallback to reasonable defaults
            return {
                'attack': 5,
                'defense': 5,
                'speed': 5,
                'special_ability': 'Survival Instinct',
                'reasoning': f'LLM generation failed: {str(e)}. Using balanced defaults.',
                'tier_recommendation': 'uu',
                'confidence': 0.3
            }
    
    def _build_reference_context(self):
        """Build formatted reference context for LLM"""
        context_parts = []
        
        for category, bugs in self.reference_dataset.items():
            context_parts.append(f"\n**{category.replace('_', ' ').title()}:**")
            for bug in bugs:
                context_parts.append(
                    f"- {bug['name']} ({bug['scientific']}): "
                    f"Size {bug['size_mm']}mm, "
                    f"ATK:{bug['attack']} DEF:{bug['defense']} SPD:{bug['speed']} "
                    f"(Total: {bug['attack']+bug['defense']+bug['speed']}) "
                    f"- {bug['reasoning']}"
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
        bug_info = {
            'scientific_name': bug.scientific_name,
            'common_name': bug.common_name,
            'size_mm': bug.species_info.average_size_mm if bug.species_info else None,
            'traits': self._extract_traits(bug),
            'species_info': bug.species_info.to_dict() if bug.species_info else None
        }
        
        stats = self.generate_stats_with_llm(bug_info)
        
        # Update bug
        bug.attack = stats['attack']
        bug.defense = stats['defense']
        bug.speed = stats['speed']
        bug.special_ability = stats.get('special_ability')
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
        # Use simple stat generation
        from app.services.taxonomy_service import StatsGenerator
        generator = StatsGenerator()
        stats = generator.generate_stats(bug)
        bug.attack = stats['attack']
        bug.defense = stats['defense']
        bug.speed = stats['speed']
        bug.special_ability = stats.get('special_ability')
    
    # Always assign tier after stats are set
    bug.tier = TierSystem.assign_tier(bug)
    bug.stats_generated = True
    
    db.session.commit()
    
    return bug