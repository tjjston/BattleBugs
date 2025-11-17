"""
Visual Lore Analyzer - Generates Secret Battle Advantages from Bug Photos
This module uses Anthropic's LLM to analyze bug images for hidden details
that can provide secret combat advantages in battles.
"""

import base64
from anthropic import Anthropic
from flask import current_app
from app import db
from app.models import Bug
import json

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
        self.client = None
    
    def _get_client(self):
        """Lazy load Anthropic client"""
        if not self.client:
            api_key = current_app.config.get('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            self.client = Anthropic(api_key=api_key)
        return self.client
    
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
        with open(image_path, 'rb') as f:
            image_data = base64.standard_b64encode(f.read()).decode('utf-8')
        
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
            client = self._get_client()
            
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ],
                    }
                ],
            )
            
            response_text = message.content[0].text
            
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            
            result = json.loads(response_text)
            
            # Validate xfactor is in range
            xfactor = float(result.get('xfactor', 0.0))
            result['xfactor'] = max(-5.0, min(5.0, xfactor))
            
            return result
            
        except Exception as e:
            print(f"Visual lore analysis error: {e}")
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
        
        print(f"🔮 SECRET LORE APPLIED to {bug.nickname}:")
        print(f"   xfactor: {bug.xfactor:+.1f}")
        print(f"   Reason: {bug.xfactor_reason}")
        print(f"   Battle hook: {analysis.get('battle_hook', 'N/A')}")
        
        return bug


def generate_lore_enhanced_battle_narrative(bug1, bug2, winner):
    """
    Enhanced battle narrative that SECRETLY incorporates visual lore
    
    The narrative subtly mentions items/advantages without being obvious
    """
    from anthropic import Anthropic
    from flask import current_app
    
    # Get secret lore (never shown to users directly)
    secret1 = bug1.get_secret_lore()
    secret2 = bug2.get_secret_lore()
    
    # Get public lore (user-provided)
    public1 = bug1.get_public_lore()
    public2 = bug2.get_public_lore()
    
    # Build narrative prompt
    prompt = f"""Generate an epic 3-paragraph battle narrative between two bug gladiators.

**{bug1.nickname}**
Stats: ATK:{bug1.attack} DEF:{bug1.defense} SPD:{bug1.speed}
Background: {public1.get('background') or 'Unknown origin'}
Motivation: {public1.get('motivation') or 'Fights for glory'}
Personality: {public1.get('personality') or 'Unknown'}

SECRET ADVANTAGES (weave these SUBTLY into narrative):
{secret1['visual_analysis']}
Items: {secret1['items_weapons']}
Environment: {secret1['environment']}
XFactor: {secret1['xfactor']:+.1f} - {secret1['xfactor_reason']}

**{bug2.nickname}**
Stats: ATK:{bug2.attack} DEF:{bug2.defense} SPD:{bug2.speed}
Background: {public2.get('background') or 'Unknown origin'}
Motivation: {public2.get('motivation') or 'Fights for glory'}
Personality: {public2.get('personality') or 'Unknown'}

SECRET ADVANTAGES (weave these SUBTLY into narrative):
{secret2['visual_analysis']}
Items: {secret2['items_weapons']}
Environment: {secret2['environment']}
XFactor: {secret2['xfactor']:+.1f} - {secret2['xfactor_reason']}

**WINNER: {winner.nickname}**

INSTRUCTIONS:
1. Write a dramatic 3-paragraph battle (Opening, Mid-battle, Climax)
2. SUBTLY incorporate the secret visual advantages WITHOUT being obvious
   - If bug has grass blade: mention "swift movements" or "precise strikes"
   - If bug has environmental advantage: describe tactical positioning
   - If bug has posture advantage: describe combat readiness
3. Use the user-provided lore (background, motivation) naturally
4. The winner's xfactor advantage should influence how they win
5. Keep under 300 words
6. DO NOT explicitly say "using the grass blade as a sword" - be subtle!

Write an exciting narrative that makes the battle memorable!
"""
    
    try:
        api_key = current_app.config.get('ANTHROPIC_API_KEY')
        if api_key:
            client = Anthropic(api_key=api_key)
            
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return message.content[0].text
    except Exception as e:
        print(f"Lore-enhanced narrative error: {e}")
    
    # Fallback
    return f"""
THE ARENA TREMBLES

{bug1.nickname} and {bug2.nickname} enter the arena, the crowd roaring with anticipation.
{bug1.nickname} {public1.get('motivation', 'prepares for battle')}, while {bug2.nickname} 
{public2.get('motivation', 'stands ready')}.

The battle begins with incredible ferocity! Both warriors employ their unique fighting styles,
drawing on their backgrounds and training. The arena floor shakes with each clash.

In a stunning finale, {winner.nickname} emerges victorious! Through skill, determination, and 
perhaps a touch of fate, victory is claimed. The crowd erupts in celebration!

Winner: {winner.nickname} 🏆
"""


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