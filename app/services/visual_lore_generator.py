"""
Visual Lore Analyzer - Generates Secret Battle Advantages from Bug Photos
This module uses Anthropic's LLM to analyze bug images for hidden details
that can provide secret combat advantages in battles.
"""

import base64
import json
import re
from flask import current_app
from app import db
from app.models import Bug


def _parse_json_safe(text: str) -> dict:
    """Try direct JSON parse first, then extract from prose."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON found in response: {text[:200]}")


class VisualLoreAnalyzer:
    """
    Analyzes bug photos to find hidden advantages
    - Items the bug is holding (grass blade = sword!)
    - Environmental features (sitting on rock = defensive position)
    - Posture/stance (aggressive vs defensive)
    - Unique physical traits not captured in stats

    Generates a secret xfactor score (-5.0 to +5.0) that subtly affects battles
    """

    def __init__(self):
        pass
    
    def analyze_for_hidden_lore(self, image_path, user_lore=None):
        """
        Analyze bug photo for secret combat advantages
        
        Args:
            image_path: Path to bug image
            user_lore: Dict of user-provided lore (optional context)
            
        Returns:
            dict with:
                - visual_lore_analysis: Full narrative analysis
                - visual_lore_items: Items/weapons found
                - visual_lore_environment: Environmental advantages
                - visual_lore_posture: Battle stance
                - visual_lore_unique_features: Special traits
                - xfactor: Float from -5.0 to +5.0
                - xfactor_reason: Why this xfactor value
        """
        media_type = self._get_media_type(image_path)
        
        lore_context = ""
        if user_lore:
            lore_context = f"""
USER-PROVIDED LORE (consider this when analyzing):
- Background: {user_lore.get('background', 'N/A')}
- Motivation: {user_lore.get('motivation', 'N/A')}
- Personality: {user_lore.get('personality', 'N/A')}
- Interests: {user_lore.get('interests', 'N/A')}
"""
        
        # Create the secret analysis prompt
        prompt = f"""You are a mystical arena sage analyzing a gladiator bug for SECRET combat advantages that only you can see.

MISSION: Look VERY CAREFULLY at this bug photo and find hidden details that could give it an edge in combat. Be creative and imaginative!

WHAT TO LOOK FOR:
1. **Items/Objects**: Is the bug holding, touching, or near any objects?
   - Blade of grass = sword
   - Stick = staff/spear
   - Rock = shield
   - Leaf = armor plate
   - Water droplet = magic source
   
2. **Environment**: What's around the bug?
   - High ground = tactical advantage
   - In shadows = stealth bonus
   - On flower = nature magic
   - Near water = hydro power
   - In sunlight = solar charging
   
3. **Posture/Stance**: How is the bug positioned?
   - Aggressive stance = ready to strike
   - Defensive posture = guardian mode
   - Climbing = agility advantage
   - Hiding = ambush potential
   - Wings spread = aerial dominance
   
4. **Unique Visual Traits**: Special physical features
   - Unusual coloration = camouflage/intimidation
   - Battle scars = veteran warrior
   - Pristine condition = untested but confident
   - Size relative to environment = power indicator

5. **Obvious Weaknesses**: Any visible disadvantages?
    - Injuries = hindered performance
    - Missing limbs = reduced capabilities
    - Immaturity = lack of experience
    - Mutational defects = vulnerabilities

{lore_context}

**CRITICAL**: This analysis is SECRET. The bug's owner will NEVER see this. Only the battle system uses it.

Respond in this EXACT JSON format (no markdown, pure JSON):
{{
  "visual_lore_analysis": "Full 2-3 sentence narrative about what you observe and how it helps in battle",
  "visual_lore_items": "Objects/items the bug has access to (or 'none')",
  "visual_lore_environment": "Environmental advantages (or 'neutral environment')",
  "visual_lore_posture": "Combat stance/readiness description",
  "visual_lore_unique_features": "Special visual traits not in base stats",
  "xfactor": 0.0-5.0 or -5.0-0.0,
  "xfactor_reason": "Why this xfactor score? What gives the advantage/disadvantage?",
  "battle_hook": "A creative way this secret advantage could manifest in battle (1 sentence)"
}}

XFACTOR SCORING GUIDE:
+3 to +5: Legendary advantages (epic items, perfect positioning, mystical energy)
+1 to +2.5: Good advantages (useful items, decent position, ready stance)
0: Neutral (nothing special)
-1 to -2.5: Disadvantages (bad position, tired/injured, vulnerable)
-3 to -5: Severe disadvantages (trapped, weak position, damaged)

Significant XFACTOR Advantages should be rare, point distribution should be centered around 0 and follow a normal distribution.

BE CREATIVE! Find interesting details. If the bug is near a twig, maybe it's a LEGENDARY STAFF. If it's in shadow, maybe it's CHANNELING DARKNESS. Make it fun!
"""
        
        try:
            from app.services.llm_manager import LLMService
            llm = LLMService()
            with open(image_path, 'rb') as f:
                image_b64 = base64.standard_b64encode(f.read()).decode('utf-8')
            response_text = llm.generate(
                prompt=prompt,
                task='vision_analysis',
                image_data={'base64': image_b64, 'media_type': media_type},
                max_tokens=1024,
                temperature=0.7,
                system_prompt="You are a mystical arena sage. Always respond with valid JSON only, no markdown.",
                json_mode=True,
            )
            if not response_text:
                raise ValueError("LLM returned empty response")
            result = _parse_json_safe(response_text)
            
            # Validate xfactor is in range
            xfactor = float(result.get('xfactor', 0.0))
            result['xfactor'] = max(-5.0, min(5.0, xfactor))
            
            return result
            
        except Exception as e:
            current_app.logger.warning("Visual lore analysis failed: %s", e)
            # Fallback - neutral analysis
            return {
                "visual_lore_analysis": "Standard bug in typical environment",
                "visual_lore_items": "none",
                "visual_lore_environment": "neutral environment",
                "visual_lore_posture": "standard stance",
                "visual_lore_unique_features": "typical physical traits",
                "xfactor": 0.0,
                "xfactor_reason": "No special visual advantages detected",
                "battle_hook": "Relies on base stats and tactics"
            }
    
    def _get_media_type(self, image_path):
        """Determine media type from file extension"""
        ext = image_path.lower().split('.')[-1]
        media_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        return media_types.get(ext, 'image/jpeg')
    
    def apply_visual_lore_to_bug(self, bug, image_path):
        """
        Analyze image and apply secret lore to bug
        
        Args:
            bug: Bug model instance
            image_path: Path to bug's image
            
        Returns:
            Updated bug with secret lore applied
        """
        # Get user lore for context
        user_lore = bug.get_public_lore() if bug else None
        
        # Analyze the image
        analysis = self.analyze_for_hidden_lore(image_path, user_lore)
        
        # Apply to bug (these fields are HIDDEN from users)
        bug.visual_lore_analysis = analysis['visual_lore_analysis']
        bug.visual_lore_items = analysis['visual_lore_items']
        bug.visual_lore_environment = analysis['visual_lore_environment']
        bug.visual_lore_posture = analysis['visual_lore_posture']
        bug.visual_lore_unique_features = analysis['visual_lore_unique_features']
        bug.xfactor = analysis['xfactor']
        bug.xfactor_reason = analysis['xfactor_reason']
        
        db.session.commit()
        
        current_app.logger.info("Secret lore applied to bug %s", bug.id)
        
        return bug


def _build_battle_prompt(bug1, bug2, winner, venue=None) -> str:
    """Compose the same prompt used by both the sync and streaming paths."""
    secret1 = bug1.get_secret_lore()
    secret2 = bug2.get_secret_lore()
    public1 = bug1.get_public_lore()
    public2 = bug2.get_public_lore()

    venue_line = ""
    if venue:
        venue_line = f"\n**Arena: {venue['name']}** — {venue['desc']}\n"

    return f"""Generate an epic 3-paragraph battle narrative between two bug gladiators.
{venue_line}
**{bug1.nickname}**
Background: {public1.get('background') or 'Unknown origin'}
Motivation: {public1.get('motivation') or 'Fights for glory'}
Personality: {public1.get('personality') or 'Unknown'}
Secret edge: {secret1['items_weapons']} | {secret1['environment']} | xfactor {secret1['xfactor']:+.1f}

**{bug2.nickname}**
Background: {public2.get('background') or 'Unknown origin'}
Motivation: {public2.get('motivation') or 'Fights for glory'}
Personality: {public2.get('personality') or 'Unknown'}
Secret edge: {secret2['items_weapons']} | {secret2['environment']} | xfactor {secret2['xfactor']:+.1f}

**WINNER: {winner.nickname}**

Write a dramatic 3-paragraph battle (Opening / Mid-battle / Climax). Use the arena setting to
establish atmosphere. Weave the secret edges SUBTLY — never name them literally. Use the lore
and personality naturally. Keep under 300 words. End with a one-line declaration of the winner."""


def generate_lore_enhanced_battle_narrative(bug1, bug2, winner, venue=None):
    """
    Enhanced battle narrative routed through LLMService (defaults to Ollama/Qwen).
    Secretly incorporates visual lore without revealing it to users.
    """
    from app.services.llm_manager import LLMService
    prompt = _build_battle_prompt(bug1, bug2, winner, venue=venue)

    try:
        llm = LLMService()
        result = llm.generate(prompt, task='battle_narrative', max_tokens=800, temperature=0.85)
        if not result or not result.strip():
            raise ValueError("LLM returned empty narrative")
        return result
    except Exception as e:
        current_app.logger.warning("Battle narrative failed: %s", e)

    return (
        f"THE ARENA TREMBLES\n\n"
        f"{bug1.nickname} and {bug2.nickname} face off before a roaring crowd. "
        f"Both fighters draw on everything that brought them here.\n\n"
        f"The clash is fierce — momentum shifts, the ground shakes, and neither side yields easily.\n\n"
        f"In the end, {winner.nickname} seizes the moment and claims victory. The crowd erupts. "
        f"{winner.nickname} wins! \U0001f3c6"
    )


# Example xfactor scenarios that could appear:
XFACTOR_EXAMPLES = {
    'grass_blade_sword': {
        'xfactor': +3.5,
        'reason': 'Wielding blade of grass as legendary weapon',
        'narrative_hint': 'swift, precise strikes with unusual accuracy'
    },
    'high_ground': {
        'xfactor': +2.0,
        'reason': 'Tactical positioning on elevated surface',
        'narrative_hint': 'superior vantage point, tactical dominance'
    },
    'shadow_stealth': {
        'xfactor': +2.5,
        'reason': 'Concealed in shadows, ambush potential',
        'narrative_hint': 'attacks from unexpected angles'
    },
    'water_droplet_magic': {
        'xfactor': +4.0,
        'reason': 'Touching water droplet - mystical hydro power',
        'narrative_hint': 'movements seem fluid, almost supernatural'
    },
    'battle_scars': {
        'xfactor': +1.5,
        'reason': 'Veteran warrior, experienced in combat',
        'narrative_hint': 'moves with battle-hardened confidence'
    },
    'vulnerable_position': {
        'xfactor': -2.0,
        'reason': 'Exposed, no cover, disadvantageous stance',
        'narrative_hint': 'struggles to find solid footing'
    },
    'injured': {
        'xfactor': -3.0,
        'reason': 'Visible damage to wings/legs',
        'narrative_hint': 'movements somewhat hindered'
    }
}
