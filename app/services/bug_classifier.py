"""
Enhanced Bug Classification with User Input Validation
Uses user's species guess as a hint, but LLM independently validates
Prevents manipulation: "This ladybug is actually a bullet ant"
"""

import json
import re
from typing import Dict, Any, Optional
from flask import current_app
from app.services.llm_manager import LLMService, LLMModel
from app.services.vision_service import ImageQualityChecker


def _extract_json(text: str) -> dict:
    """Parse JSON from an LLM response, tolerating prose before/after the object."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    if text:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    raise ValueError(f"No parseable JSON in LLM response: {(text or '')[:200]}")


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
        
        # Physical condition
        self.condition = data.get('condition', 'alive') or 'alive'
        self.condition_notes = data.get('condition_notes', '')

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
        self.min_confidence = current_app.config.get('HF_BUG_CLASSIFIER_MIN_CONFIDENCE', 0.60)
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

        # Step 2: Local Hugging Face image classifier.
        # ph0masta/bug_classifier predicts insect/spider genera, so a confident
        # prediction is treated as approval. Low-confidence predictions reject
        # obvious negatives before slower LLM work.
        hf_result = self._huggingface_analysis(
            image_path=image_path,
            user_species_guess=user_species_guess,
        )
        if hf_result is not None:
            if hf_result.approved:
                duplicate_check = self._check_for_duplicates(image_path, user_id)
                if duplicate_check['is_duplicate']:
                    hf_result.approved = False
                    hf_result.rejection_reasons.append(
                        f"Duplicate of existing bug: {duplicate_check['duplicate_bug_name']}"
                    )
                    hf_result.reasoning += f"\n\nDuplicate detected: {duplicate_check['similarity_score']:.0%} similar."
                else:
                    hf_result = self._normalize_species_via_backbone(hf_result)
            return hf_result
        
        # Step 3: LLM fallback with User Hint
        llm_result = self._llm_comprehensive_analysis(
            image_path=image_path,
            nickname=nickname,
            description=user_description,
            user_species_guess=user_species_guess,  # Pass as hint
            preflight_warnings=preflight_result.get('warnings', [])
        )
        
        # Step 4: Duplicate check (only if LLM approved)
        if llm_result.approved:
            duplicate_check = self._check_for_duplicates(image_path, user_id)
            if duplicate_check['is_duplicate']:
                llm_result.approved = False
                llm_result.rejection_reasons.append(
                    f"Duplicate of existing bug: {duplicate_check['duplicate_bug_name']}"
                )
                llm_result.reasoning += f"\n\nDuplicate detected: {duplicate_check['similarity_score']:.0%} similar."

        # Step 5: Normalise species name via GBIF backbone (synonym resolution + fill order/family)
        if llm_result.approved:
            llm_result = self._normalize_species_via_backbone(llm_result)

        return llm_result

    def _huggingface_analysis(
        self,
        image_path: str,
        user_species_guess: Optional[str],
    ) -> Optional[BugClassificationResult]:
        # Check admin DB override first, then fall back to app config
        try:
            from app.models import SystemSetting
            db_enabled = SystemSetting.get('classifier_enabled')
            if db_enabled is not None:
                enabled = db_enabled.lower() != 'false'
            else:
                enabled = current_app.config.get('HF_BUG_CLASSIFIER_ENABLED', True)
        except Exception:
            enabled = current_app.config.get('HF_BUG_CLASSIFIER_ENABLED', True)
        if not enabled:
            return None

        # Also apply classifier URL override from DB settings
        try:
            from app.models import SystemSetting
            db_url = SystemSetting.get('classifier_url')
            if db_url:
                current_app.config['BUG_CLASSIFIER_URL'] = db_url
        except Exception:
            pass

        from app.services.huggingface_bug_classifier import HuggingFaceBugClassifier

        prediction = HuggingFaceBugClassifier().classify(image_path)
        if not prediction.available:
            try:
                from app.models import SystemSetting
                db_required = SystemSetting.get('classifier_required')
                required = (db_required == 'true') if db_required is not None else current_app.config.get('HF_BUG_CLASSIFIER_REQUIRED', False)
            except Exception:
                required = current_app.config.get('HF_BUG_CLASSIFIER_REQUIRED', False)
            if required:
                return BugClassificationResult({
                    'approved': False,
                    'confidence': 0.0,
                    'is_arthropod': False,
                    'rejection_reasons': [f'Hugging Face classifier unavailable: {prediction.error}'],
                    'reasoning': 'Local Hugging Face classifier is required but could not run.',
                    'quality_assessment': 'Image quality not assessed by classifier.',
                    'llm_provider': 'huggingface',
                    'llm_model': current_app.config.get('HF_BUG_CLASSIFIER_MODEL', 'ph0masta/bug_classifier'),
                })
            return None

        label = prediction.label or 'unknown genus'
        warnings = [
            f"Hugging Face classifier prediction: {label} ({prediction.confidence:.0%})."
        ]

        user_guess_matches = None
        user_guess_feedback = ''
        if user_species_guess:
            user_guess_matches = label.lower() in user_species_guess.lower() or user_species_guess.lower() in label.lower()
            if user_guess_matches:
                user_guess_feedback = f"Your guess is close to the model prediction: {label}."
            else:
                user_guess_feedback = f"The local classifier predicted {label}; your guess was kept as a hint only."

        if not prediction.approved:
            # Low confidence: let the LLM make the call instead of hard-rejecting.
            # The HF model is narrow (specific genera) and poorly calibrated for
            # real-world photos — 20-40% on a genuine bug is common. Pass through.
            current_app.logger.info(
                "HF classifier confidence %.0f%% below threshold — deferring to LLM.",
                prediction.confidence * 100,
            )
            return None

        return BugClassificationResult({
            'approved': True,
            'confidence': prediction.confidence,
            'is_arthropod': True,
            'identified_species': label,
            'common_name': label,
            'scientific_name': label,
            'order': None,
            'family': None,
            'user_guess_matches': user_guess_matches,
            'user_guess_feedback': user_guess_feedback,
            'reasoning': f"Local Hugging Face classifier identified the image as {label}.",
            'quality_assessment': 'Accepted by local image classifier.',
            'rejection_reasons': [],
            'warnings': warnings,
            'llm_provider': 'huggingface',
            'llm_model': current_app.config.get('HF_BUG_CLASSIFIER_MODEL', 'ph0masta/bug_classifier'),
        })
    
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

        # AI-generation heuristic: check EXIF for camera metadata.
        # Real photos from phones/cameras always contain Make/Model or DateTimeOriginal.
        # Synthetic AI images typically have no EXIF at all.
        try:
            from PIL import Image as _PILImage
            from PIL.ExifTags import TAGS as _EXIF_TAGS
            _img = _PILImage.open(image_path)
            raw_exif = _img._getexif() if hasattr(_img, '_getexif') else None
            if raw_exif:
                exif = {_EXIF_TAGS.get(k, k): v for k, v in raw_exif.items()}
                has_camera = bool(exif.get('Make') or exif.get('Model') or exif.get('DateTimeOriginal'))
            else:
                has_camera = False

            if not has_camera:
                result['warnings'].append(
                    'No camera EXIF metadata found. If this is an AI-generated image it will be '
                    'rejected during LLM review. Real phone/camera photos normally include this data.'
                )
        except Exception:
            pass  # non-JPEG formats may not have EXIF; don't fail preflight

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
        current_app.logger.info(
            "CLASSIFY using model provider=%s model=%s image=%s",
            model.provider, model.model_name, image_path,
        )

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

            if not response:
                raise ValueError("LLM returned empty response")

            result_data = _extract_json(response)
            result_data['llm_provider'] = model.provider
            result_data['llm_model'] = model.model_name
            current_app.logger.info(
                "CLASSIFY result — approved=%s confidence=%.2f species=%s",
                result_data.get('approved'), result_data.get('confidence'),
                result_data.get('identified_species'),
            )
            return BugClassificationResult(result_data)

        except Exception as e:
            current_app.logger.warning(
                "CLASSIFY failed (provider=%s model=%s) — %s: %s — falling back to manual review",
                model.provider, model.model_name, type(e).__name__, e,
            )
            # Don't hard-reject when the classifier itself fails; queue for human review instead.
            return BugClassificationResult({
                'approved': True,
                'confidence': 0.5,
                'is_arthropod': True,
                'reasoning': 'Automatic vision classification unavailable; submission queued for admin review.',
                'quality_assessment': 'Not assessed',
                'rejection_reasons': [],
                'warnings': [
                    'The AI classifier could not process this image automatically. '
                    'An admin will review your submission shortly.'
                ],
                'llm_provider': 'fallback',
                'llm_model': 'manual_review',
            })

    def _normalize_species_via_backbone(self, result: BugClassificationResult) -> BugClassificationResult:
        """
        After LLM or HF classification, run the GBIF backbone to:
          - Resolve synonyms to accepted canonical names
          - Fill in missing order/family if only genus was identified
          - Boost confidence when backbone confirms the name
        """
        if not result.scientific_name and not result.identified_species:
            return result
        name = result.scientific_name or result.identified_species
        try:
            from app.services.taxonomy import GBIFBackbone
            match = GBIFBackbone().resolve_accepted(name)
            if not match:
                return result
            canonical = match.get('canonicalName') or name
            if canonical != name:
                current_app.logger.info("CLASSIFY backbone: %r → canonical %r (conf=%s)",
                                        name, canonical, match.get('confidence'))
            result.scientific_name = canonical
            if not result.order and match.get('order'):
                result.order = match['order']
            if not result.family and match.get('family'):
                result.family = match['family']
        except Exception as exc:
            current_app.logger.debug("backbone normalisation skipped: %s", exc)
        return result
    
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
- Photo appears to be a real specimen photograph (phone camera, DSLR, macro shot)
- Confidence >= 60%
- If user provided species guess: it's reasonably accurate (same order/family)
- Dead, squashed, or damaged specimens are ALL accepted — condition is recorded and affects stats
- Imperfect photos (slight blur, harsh flash, busy background) are fine as long as the bug is identifiable

❌ **REJECT if:**
- Not an arthropod (vertebrates, mollusks, worms, etc.)
- Image is drawing, illustration, toy, or CGI
- Image appears AI-generated (overly perfect lighting, surreal details, texture artifacts, impossible anatomy, missing EXIF noted in warnings)
- Bug too small/blurry/dark to identify
- Multiple bugs (must be single specimen)
- Poor image quality
- Confidence < 75%
- **User's species guess is wildly inaccurate** (suggests manipulation attempt)

🤖 **AI IMAGE DETECTION:**
Look for these signs of AI generation and REJECT if present:
- Unnaturally perfect, uniform lighting with no shadows or harsh flash
- Background is suspiciously clean, blurred, or AI-bokeh
- Anatomically impossible features (extra legs, merged body parts, impossible symmetry)
- Texture looks "painted" or lacks the grain/noise of real photos
- The pre-flight warnings mention missing EXIF camera metadata
Real insect photos taken by phones/cameras have slight blur, natural backgrounds, visible grain, and imperfect lighting.

🐛 **PHYSICAL CONDITION ASSESSMENT (required for all submissions):**
Assess the bug's physical state and set `condition` to one of:
- `alive` — Bug appears alive and fully intact
- `dead` — Bug is dead but body is largely whole (will undergo Zombugification — stat modifiers applied)
- `squashed` — Bug is visibly crushed, flattened, or severely deformed
- `damaged_wings` — Wings are visibly torn, missing, or broken; body otherwise intact
- `damaged_legs` — One or more legs are missing or broken; body otherwise intact
- `damaged` — Other visible damage (scarring, missing antennae, general wear)

In `condition_notes`, describe specifically what you observed about the specimen's physical state in 1–2 sentences.

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
  "warnings": ["Any concerns even if approved, empty if none"],
  "condition": "alive|dead|squashed|damaged_wings|damaged_legs|damaged",
  "condition_notes": "1-2 sentences describing the specimen's physical state"
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
- Confidence must be >= 0.60 to approve
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
                return LLMModel.QWEN36_35B
        
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
