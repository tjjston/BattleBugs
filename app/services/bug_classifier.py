"""
LLM-Controlled Bug Classification System
Gives final authority to LLM for bug submission approval with multi-provider support
"""

from typing import Dict, Any, Optional
from flask import current_app
from app.services.llm_manager import LLMService, LLMModel
from app.services.vision_service import VisionService, ImageQualityChecker
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
            'reasoning': self.reasoning,
            'quality_assessment': self.quality_assessment,
            'rejection_reasons': self.rejection_reasons,
            'warnings': self.warnings,
            'llm_provider': self.llm_provider,
            'llm_model': self.llm_model
        }


class LLMBugClassifier:
    """
    LLM-powered bug classification with final authority
    
    Supports multiple LLM providers:
    - Anthropic Claude (default, best vision)
    - OpenAI GPT-4 Vision (good alternative)
    - Local Ollama models (for offline/privacy)
    """
    
    def __init__(self, preferred_provider: Optional[str] = None):
        """
        Initialize classifier
        
        Args:
            preferred_provider: 'anthropic', 'openai', or 'ollama'
                               If None, uses config default
        """
        self.llm = LLMService()
        self.quality_checker = ImageQualityChecker()
        self.preferred_provider = preferred_provider
        
        # Minimum requirements (pre-LLM checks)
        self.min_confidence = 0.75
        self.min_image_width = 400
        self.min_image_height = 400
        self.max_file_size_mb = 16
    
    def classify_bug_submission(
        self, 
        image_path: str, 
        user_id: int,
        nickname: str = None,
        user_description: str = None
    ) -> BugClassificationResult:
        """
        Complete bug classification with LLM having final say
        
        Args:
            image_path: Path to uploaded image
            user_id: ID of submitting user
            nickname: User's name for the bug
            user_description: User's description
            
        Returns:
            BugClassificationResult with approval decision and metadata
        """
        
        # Step 1: Pre-flight checks (fast rejection of obviously bad submissions)
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
        
        # Step 2: LLM Analysis (FINAL AUTHORITY)
        llm_result = self._llm_comprehensive_analysis(
            image_path=image_path,
            nickname=nickname,
            description=user_description,
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
                llm_result.reasoning += f"\n\nDuplicate detected: {duplicate_check['similarity_score']:.0%} similar to existing submission."
        
        return llm_result
    
    def _preflight_checks(self, image_path: str) -> Dict[str, Any]:
        """
        Fast, non-LLM checks for obvious disqualifiers
        Returns dict with 'passed', 'issues', 'warnings'
        """
        result = {
            'passed': True,
            'issues': [],
            'warnings': []
        }
        
        # Check file format
        format_check = self.quality_checker.check_format(image_path)
        if not format_check['passes']:
            result['passed'] = False
            result['issues'].append(format_check['issue'])
        
        # Check resolution
        resolution_check = self.quality_checker.check_resolution(
            image_path, 
            self.min_image_width, 
            self.min_image_height
        )
        if not resolution_check['passes']:
            result['passed'] = False
            result['issues'].append(resolution_check['issue'])
        
        # Check file size
        size_check = self.quality_checker.check_file_size(
            image_path, 
            self.max_file_size_mb
        )
        if not size_check['passes']:
            result['passed'] = False
            result['issues'].append(size_check['issue'])
        elif size_check['size_mb'] > 10:
            result['warnings'].append(f"Large file size: {size_check['size_mb']:.1f}MB")
        
        return result
    
    def _llm_comprehensive_analysis(
        self,
        image_path: str,
        nickname: Optional[str],
        description: Optional[str],
        preflight_warnings: list
    ) -> BugClassificationResult:
        """
        Send image to LLM for comprehensive analysis
        LLM has FINAL AUTHORITY on approval
        """
        
        # Build the prompt
        prompt = self._build_classification_prompt(
            nickname=nickname,
            description=description,
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
            # Call LLM with vision
            response = self.llm.generate(
                prompt=prompt,
                task='vision_analysis',
                model=model,
                image_data={'base64': image_data, 'media_type': media_type},
                max_tokens=1500,
                temperature=0.3,  # Lower temperature for classification
                json_mode=True
            )
            
            # Parse response
            result_data = json.loads(response)
            
            # Add provider metadata
            result_data['llm_provider'] = model.provider
            result_data['llm_model'] = model.model_name
            
            return BugClassificationResult(result_data)
            
        except Exception as e:
            print(f"LLM classification error: {e}")
            
            # Fallback: reject with error
            return BugClassificationResult({
                'approved': False,
                'confidence': 0.0,
                'rejection_reasons': [f'LLM classification failed: {str(e)}'],
                'reasoning': 'Unable to complete classification due to technical error',
                'llm_provider': 'error',
                'llm_model': 'failed'
            })
    
    def _build_classification_prompt(
        self,
        nickname: Optional[str],
        description: Optional[str],
        preflight_warnings: list
    ) -> str:
        """Build the classification prompt for the LLM"""
        
        prompt = f"""You are the FINAL AUTHORITY on bug submission classification for a bug battle arena game.

Your job: Analyze this image and determine if it should be APPROVED or REJECTED for the arena.

**Submission Context:**
{f"User's chosen name: {nickname}" if nickname else "No name provided yet"}
{f"User's description: {description}" if description else "No description provided"}
{f"Pre-flight warnings: {', '.join(preflight_warnings)}" if preflight_warnings else "No pre-flight issues"}

**APPROVAL CRITERIA:**

✅ **APPROVE if:**
- Image clearly shows an arthropod (insect, arachnid, myriapod, crustacean)
- Bug is the main subject of the photo
- Image quality is sufficient to identify distinguishing features
- Photo appears to be of a real specimen (not drawing/toy/CGI)
- Confidence >= 75%

❌ **REJECT if:**
- Not an arthropod (vertebrates, mollusks, worms, etc.)
- Image is a drawing, illustration, toy, or CGI
- Bug is too small/blurry/dark to identify
- Multiple bugs (must be single specimen)
- Image quality is too poor
- Confidence < 75%

⚠️ **SPECIAL CASES:**
- Dead specimens are OK (arena is for photos, not live battles)
- Preserved/pinned specimens are OK
- Partial specimens (missing legs) are OK if identifiable
- Uncommon angles are OK if arthropod features are visible

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
  "reasoning": "2-3 sentence explanation of your decision",
  "quality_assessment": "Brief assessment of image quality",
  "rejection_reasons": ["List specific reasons if rejected, empty array if approved"],
  "warnings": ["Any concerns even if approved, empty array if none"]
}}

**IMPORTANT:**
- You have FINAL AUTHORITY - if you reject, it's rejected
- Be strict but fair - arena needs quality submissions
- Confidence must be >= 0.75 to approve
- If unsure between approve/reject, REJECT (better safe than sorry)

Analyze the image now and respond with your classification decision."""

        return prompt
    
    def _get_preferred_model(self) -> 'LLMModel':
        """Determine which LLM model to use"""
        from app.services.llm_manager import LLMModel, LLMConfig
        
        if self.preferred_provider:
            # Use specified provider
            if self.preferred_provider == 'anthropic':
                return LLMModel.CLAUDE_SONNET_4
            elif self.preferred_provider == 'openai':
                return LLMModel.GPT_4
            elif self.preferred_provider == 'ollama':
                return LLMModel.LLAMA3  # Or whatever local model is configured
        
        # Use config default
        return LLMConfig.get_model_for_task('vision_analysis')
    
    def _check_for_duplicates(self, image_path: str, user_id: int) -> Dict[str, Any]:
        """Check if this bug was already submitted by this user"""
        vision = VisionService()
        return vision.check_duplicate_bug(image_path, user_id)


# Convenience function for routes
def classify_bug_submission(
    image_path: str,
    user_id: int,
    nickname: str = None,
    description: str = None,
    preferred_provider: str = None
) -> BugClassificationResult:
    """
    Convenience function to classify a bug submission
    
    Usage in routes:
        result = classify_bug_submission(
            image_path='/path/to/image.jpg',
            user_id=current_user.id,
            nickname='Thunder Beetle',
            description='Found in my backyard'
        )
        
        if result.approved:
            # Create bug entry
            pass
        else:
            # Show rejection reasons
            flash(f"Rejected: {'; '.join(result.rejection_reasons)}")
    """
    classifier = LLMBugClassifier(preferred_provider=preferred_provider)
    return classifier.classify_bug_submission(
        image_path=image_path,
        user_id=user_id,
        nickname=nickname,
        user_description=description
    )