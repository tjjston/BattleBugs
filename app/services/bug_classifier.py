"""
Enhanced Bug Classification with User Input Validation
Uses user's species guess as a hint, but LLM independently validates
Prevents manipulation: "This ladybug is actually a bullet ant"
"""

from typing import Dict, Any, Optional
from flask import current_app
from app.services.llm_manager import LLMService, LLMModel
from app.services.vision_service import ImageQualityChecker
import json


class BugClassificationResult:
    """Structured result from bug classification"""
    
    def __init__(self, data: Dict[str, Any]):
        self.approved = data.get('approved', False)
        self.confidence = data.get('confidence', 0.0)
        self.is_arthropod = data.get('is_arthropod', False)
        self.identified_species = data.get('identified_species')
        self.common_name = data.get('common_name')
        self.scientific_name = data.get('scientific_name')
        self.order = data.get('order')
        self.family = data.get('family')
        
        # User input validation
        self.user_guess_matches = data.get('user_guess_matches', None)
        self.user_guess_feedback = data.get('user_guess_feedback', '')
        
        # Classification reasoning
        self.reasoning = data.get('reasoning', '')
        self.quality_assessment = data.get('quality_assessment', '')
        
        # Issues and warnings
        self.rejection_reasons = data.get('rejection_reasons', [])
        self.warnings = data.get('warnings', [])
        
        # Metadata
        self.llm_provider = data.get('llm_provider', 'unknown')
        self.llm_model = data.get('llm_model', 'unknown')
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/API responses"""
        return {
            'approved': self.approved,
            'confidence': self.confidence,
            'is_arthropod': self.is_arthropod,
            'identified_species': self.identified_species,
            'common_name': self.common_name,
            'scientific_name': self.scientific_name,
            'order': self.order,
            'family': self.family,
            'user_guess_matches': self.user_guess_matches,
            'user_guess_feedback': self.user_guess_feedback,
            'reasoning': self.reasoning,
            'quality_assessment': self.quality_assessment,
            'rejection_reasons': self.rejection_reasons,
            'warnings': self.warnings,
            'llm_provider': self.llm_provider,
            'llm_model': self.llm_model
        }


class LLMBugClassifier:
    """
    LLM-powered bug classification with user input validation
    
    User's species guess helps LLM but cannot manipulate classification
    """
    
    def __init__(self, preferred_provider: Optional[str] = None):
        self.llm = LLMService()
        self.quality_checker = ImageQualityChecker()
        self.preferred_provider = preferred_provider
                # Strict mode (reject if guess is wrong order)
        #self.validation_strictness = 'order'
        
        # Moderate mode (allow if same class)
        self.validation_strictness = 'class'
        
        # Lenient mode (only reject if completely wrong)
        #self.validation_strictness = 'phylum'
        
        # Minimum requirements
        self.min_confidence = 0.75
        self.min_image_width = 400
        self.min_image_height = 400
        self.max_file_size_mb = 16
    
    def classify_bug_submission(
        self, 
        image_path: str, 
        user_id: int,
        nickname: str = None,
        user_description: str = None,
        user_species_guess: str = None  # NEW: User's guess
    ) -> BugClassificationResult:
        """
        Complete bug classification with optional user species hint
        
        Args:
            image_path: Path to uploaded image
            user_id: ID of submitting user
            nickname: User's name for the bug
            user_description: User's description
            user_species_guess: User's guess at species (HINT ONLY - validated)
            
        Returns:
            BugClassificationResult with approval decision and validation
        """
        
        # Step 1: Pre-flight checks
        preflight_result = self._preflight_checks(image_path)
        if not preflight_result['passed']:
            return BugClassificationResult({
                'approved': False,
                'confidence': 0.0,
                'rejection_reasons': preflight_result['issues'],
                'reasoning': 'Failed pre-flight quality checks',
                'llm_provider': 'none',
                'llm_model': 'preflight_only'
            })
        
        # Step 2: LLM Analysis with User Hint (FINAL AUTHORITY)
        llm_result = self._llm_comprehensive_analysis(
            image_path=image_path,
            nickname=nickname,
            description=user_description,
            user_species_guess=user_species_guess,  # Pass as hint
            preflight_warnings=preflight_result.get('warnings', [])
        )
        
        # Step 3: Duplicate check (only if LLM approved)
        if llm_result.approved:
            duplicate_check = self._check_for_duplicates(image_path, user_id)
            if duplicate_check['is_duplicate']:
                llm_result.approved = False
                llm_result.rejection_reasons.append(
                    f"Duplicate of existing bug: {duplicate_check['duplicate_bug_name']}"
                )
                llm_result.reasoning += f"\n\nDuplicate detected: {duplicate_check['similarity_score']:.0%} similar."
        
        return llm_result
    
    def _preflight_checks(self, image_path: str) -> Dict[str, Any]:
        """Fast, non-LLM checks for obvious disqualifiers"""
        result = {
            'passed': True,
            'issues': [],
            'warnings': []
        }
        
        format_check = self.quality_checker.check_format(image_path)
        if not format_check['passes']:
            result['passed'] = False
            result['issues'].append(format_check['issue'])
        
        resolution_check = self.quality_checker.check_resolution(
            image_path, self.min_image_width, self.min_image_height
        )
        if not resolution_check['passes']:
            result['passed'] = False
            result['issues'].append(resolution_check['issue'])
        
        size_check = self.quality_checker.check_file_size(
            image_path, self.max_file_size_mb
        )
        if not size_check['passes']:
            result['passed'] = False
            result['issues'].append(size_check['issue'])
        
        return result
    
    def _llm_comprehensive_analysis(
        self,
        image_path: str,
        nickname: Optional[str],
        description: Optional[str],
        user_species_guess: Optional[str],
        preflight_warnings: list
    ) -> BugClassificationResult:
        """
        Send image to LLM with user hint for validation
        LLM has FINAL AUTHORITY - user guess is just a hint
        """
        
        # Build the prompt
        prompt = self._build_classification_prompt(
            nickname=nickname,
            description=description,
            user_species_guess=user_species_guess,
            preflight_warnings=preflight_warnings
        )
        
        # Prepare image data
        import base64
        with open(image_path, 'rb') as f:
            image_data = base64.standard_b64encode(f.read()).decode('utf-8')
        
        # Determine media type
        ext = image_path.lower().split('.')[-1]
        media_types = {
            'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
            'png': 'image/png', 'gif': 'image/gif', 'webp': 'image/webp'
        }
        media_type = media_types.get(ext, 'image/jpeg')
        
        # Get model preference
        model = self._get_preferred_model()
        
        try:
            response = self.llm.generate(
                prompt=prompt,
                task='vision_analysis',
                model=model,
                image_data={'base64': image_data, 'media_type': media_type},
                max_tokens=1500,
                temperature=0.3,
                json_mode=True
            )
            
            result_data = json.loads(response)
            
            # Add provider metadata
            result_data['llm_provider'] = model.provider
            result_data['llm_model'] = model.model_name
            
            return BugClassificationResult(result_data)
            
        except Exception as e:
            print(f"LLM classification error: {e}")
            
            return BugClassificationResult({
                'approved': False,
                'confidence': 0.0,
                'rejection_reasons': [f'LLM classification failed: {str(e)}'],
                'reasoning': 'Unable to complete classification',
                'llm_provider': 'error',
                'llm_model': 'failed'
            })
    
    def _build_classification_prompt(
        self,
        nickname: Optional[str],
        description: Optional[str],
        user_species_guess: Optional[str],
        preflight_warnings: list
    ) -> str:
        """Build classification prompt with user hint validation"""
        
        # Build user hint section
        user_hint_section = ""
        if user_species_guess:
            user_hint_section = f"""

**USER'S SPECIES GUESS (HINT ONLY - YOU MUST VALIDATE):**
The user believes this might be: "{user_species_guess}"

⚠️ **CRITICAL VALIDATION RULES:**
1. **Independently verify** what you see in the image
2. **Cross-reference** the user's guess with visual evidence
3. **REJECT if major mismatch** (e.g., user says "bullet ant" but you see a ladybug)
4. **Accept if reasonable match** (e.g., user says "beetle" and you see a beetle)
5. **Provide feedback** on whether the guess was accurate

**Anti-Manipulation Check:**
- If user's guess is drastically wrong (different order/family), flag as suspicious
- Users cannot change stats by misidentifying their bug
- Base your decision on WHAT YOU SEE, not what user claims
"""

        prompt = f"""You are the FINAL AUTHORITY on bug submission classification for a bug battle arena game.

Your job: Analyze this image and determine if it should be APPROVED or REJECTED.

**Submission Context:**
{f"User's chosen name: {nickname}" if nickname else "No name provided yet"}
{f"User's description: {description}" if description else "No description provided"}
{f"Pre-flight warnings: {', '.join(preflight_warnings)}" if preflight_warnings else "No pre-flight issues"}
{user_hint_section}

**APPROVAL CRITERIA:**

✅ **APPROVE if:**
- Image clearly shows an arthropod (insect, arachnid, myriapod, crustacean)
- Bug is the main subject of the photo
- Image quality sufficient to identify distinguishing features
- Photo appears to be of real specimen (not drawing/toy/CGI)
- Confidence >= 75%
- If user provided species guess: it's reasonably accurate (same order/family)

❌ **REJECT if:**
- Not an arthropod (vertebrates, mollusks, worms, etc.)
- Image is drawing, illustration, toy, or CGI
- Bug too small/blurry/dark to identify
- Multiple bugs (must be single specimen)
- Poor image quality
- Confidence < 75%
- **User's species guess is wildly inaccurate** (suggests manipulation attempt)

⚠️ **MANIPULATION DETECTION:**
If user's guess is wrong by more than one taxonomic level:
- Example: User says "bullet ant" but image shows "ladybug" → REJECT + flag manipulation
- Example: User says "beetle" but image shows "weevil" (both Coleoptera) → APPROVE + gentle correction
- Example: User says "wasp" but image shows "bee" (both Hymenoptera) → APPROVE + note difference

**YOUR RESPONSE FORMAT (JSON only, no markdown):**
{{
  "approved": true/false,
  "confidence": 0.0-1.0,
  "is_arthropod": true/false,
  "identified_species": "Scientific name if known, else null",
  "common_name": "Common name if known, else null",
  "scientific_name": "Scientific name if known, else null",
  "order": "Taxonomic order (e.g., Coleoptera, Hymenoptera)",
  "family": "Taxonomic family if identifiable",
  "user_guess_matches": true/false/null (null if no guess provided),
  "user_guess_feedback": "How accurate was the user's guess? Helpful feedback.",
  "reasoning": "2-3 sentences explaining decision",
  "quality_assessment": "Brief image quality assessment",
  "rejection_reasons": ["List specific reasons if rejected, empty if approved"],
  "warnings": ["Any concerns even if approved, empty if none"]
}}

**EXAMPLES OF USER_GUESS_FEEDBACK:**

Good guess scenarios:
- "✅ Correct! This is indeed a Hercules beetle (Dynastes hercules)."
- "✅ Close! This is a ground beetle (Carabidae), which is in the same order (Coleoptera) as your guess."
- "✅ Good eye! Your identification of 'jumping spider' is spot on."

Incorrect but honest scenarios:
- "❌ Not quite - you guessed 'wasp' but this is actually a hover fly (mimics wasps). Both are insects, common mistake!"
- "❌ This appears to be a moth, not a butterfly as guessed. Both are Lepidoptera though!"

Manipulation attempt scenarios:
- "🚨 MANIPULATION DETECTED: You claimed this is a 'bullet ant' but the image clearly shows a ladybug. These are entirely different orders (Hymenoptera vs Coleoptera). Rejected."
- "🚨 SUSPICIOUS: You identified this as a 'mantis' but it's clearly a grasshopper. This seems like an attempt to get better stats. Rejected."

**IMPORTANT:**
- You have FINAL AUTHORITY - if you reject, it's rejected
- User's guess is a HINT, not truth
- Base decision on WHAT YOU SEE in the image
- Confidence must be >= 0.75 to approve
- Prevent stat manipulation through misidentification

Analyze the image now and respond with your classification decision."""

        return prompt
    
    def _get_preferred_model(self) -> 'LLMModel':
        """Determine which LLM model to use"""
        from app.services.llm_manager import LLMModel, LLMConfig
        
        if self.preferred_provider:
            if self.preferred_provider == 'anthropic':
                return LLMModel.CLAUDE_SONNET_4
            elif self.preferred_provider == 'openai':
                return LLMModel.GPT_4
            elif self.preferred_provider == 'ollama':
                return LLMModel.LLAMA3_VISION
        
        return LLMConfig.get_model_for_task('vision_analysis')
    
    def _check_for_duplicates(self, image_path: str, user_id: int) -> Dict[str, Any]:
        """Check if this bug was already submitted by this user"""
        from app.services.vision_service import VisionService
        vision = VisionService()
        return vision.check_duplicate_bug(image_path, user_id)


def classify_bug_submission(
    image_path: str,
    user_id: int,
    nickname: str = None,
    description: str = None,
    user_species_guess: str = None,  # NEW parameter
    preferred_provider: str = None
) -> BugClassificationResult:
    """
    Convenience function to classify a bug submission with user hint
    
    Usage in routes:
        result = classify_bug_submission(
            image_path='/path/to/image.jpg',
            user_id=current_user.id,
            nickname='Thunder Beetle',
            description='Found in my backyard',
            user_species_guess='Hercules beetle'  # User's guess (validated)
        )
        
        if result.approved:
            # Show feedback on user's guess
            if result.user_guess_matches:
                flash(f"✅ Great ID! {result.user_guess_feedback}", 'success')
            elif result.user_guess_matches is False:
                flash(f"ℹ️ {result.user_guess_feedback}", 'info')
        else:
            # Show rejection
            flash(f"Rejected: {'; '.join(result.rejection_reasons)}", 'danger')
    """
    classifier = LLMBugClassifier(preferred_provider=preferred_provider)
    
    return classifier.classify_bug_submission(
        image_path=image_path,
        user_id=user_id,
        nickname=nickname,
        user_description=description,
        user_species_guess=user_species_guess
    )
