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
        self.validation_strictness = 'class'
        self.min_confidence = current_app.config.get('HF_BUG_CLASSIFIER_MIN_CONFIDENCE', 0.80)
        self.min_image_width = 400
        self.min_image_height = 400
        self.max_file_size_mb = 16
        self._poseidon_hint: Optional[Dict[str, Any]] = None
        self._poseidon_candidates: list[Dict[str, Any]] = []
    
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
        
        log = current_app.logger
        log.info(
            "CLASSIFY [step 0/5] START — user=%s file=%s nickname=%r guess=%r",
            user_id, image_path, nickname, user_species_guess,
        )

        # Step 1: Pre-flight checks
        log.info("CLASSIFY [step 1/5] PREFLIGHT — checking format, resolution, size, EXIF")
        preflight_result = self._preflight_checks(image_path)
        if preflight_result['passed']:
            log.info("CLASSIFY [step 1/5] PREFLIGHT passed — warnings: %s",
                     preflight_result.get('warnings') or 'none')
        else:
            log.warning("CLASSIFY [step 1/5] PREFLIGHT FAILED — issues: %s",
                        preflight_result['issues'])
            return BugClassificationResult({
                'approved': False,
                'confidence': 0.0,
                'rejection_reasons': preflight_result['issues'],
                'reasoning': 'Failed pre-flight quality checks',
                'llm_provider': 'none',
                'llm_model': 'preflight_only'
            })

        # Step 2: Poseidon image classifier (ViT species-level → genus fallback)
        log.info("CLASSIFY [step 2/5] POSEIDON CLASSIFIER — calling pipeline.classify()")
        hf_result = self._huggingface_analysis(
            image_path=image_path,
            user_species_guess=user_species_guess,
        )
        if hf_result is not None:
            log.info(
                "CLASSIFY [step 2/5] POSEIDON returned result — approved=%s confidence=%.2f species=%r",
                hf_result.approved, hf_result.confidence, hf_result.scientific_name,
            )
            if hf_result.approved:
                log.info("CLASSIFY [step 2/5] POSEIDON approved — running duplicate check")
                duplicate_check = self._check_for_duplicates(image_path, user_id)
                if duplicate_check['is_duplicate']:
                    log.warning(
                        "CLASSIFY [step 2/5] DUPLICATE detected — %s (similarity=%.0f%%)",
                        duplicate_check['duplicate_bug_name'],
                        duplicate_check['similarity_score'] * 100,
                    )
                    hf_result.approved = False
                    hf_result.rejection_reasons.append(
                        f"Duplicate of existing bug: {duplicate_check['duplicate_bug_name']}"
                    )
                    hf_result.reasoning += f"\n\nDuplicate detected: {duplicate_check['similarity_score']:.0%} similar."
                else:
                    log.info("CLASSIFY [step 2/5] No duplicate — running GBIF backbone normalisation")
                    hf_result = self._normalize_species_via_backbone(hf_result)
            log.info(
                "CLASSIFY [step 2/5] DONE (no LLM) — approved=%s species=%r order=%r family=%r",
                hf_result.approved, hf_result.scientific_name, hf_result.order, hf_result.family,
            )
            return hf_result

        # Step 3: LLM vision analysis (Poseidon confidence too low or unavailable)
        poseidon_hint_str = (
            f"{self._poseidon_hint['scientific_name']} @ {self._poseidon_hint['confidence']:.0%} ({self._poseidon_hint['source']})"
            if self._poseidon_hint else "none"
        )
        log.info(
            "CLASSIFY [step 3/5] LLM VISION — Poseidon confidence too low; falling back to LLM "
            "(poseidon_hint=%s, preflight_warnings=%s)",
            poseidon_hint_str, preflight_result.get('warnings') or 'none',
        )
        llm_result = self._llm_comprehensive_analysis(
            image_path=image_path,
            nickname=nickname,
            description=user_description,
            user_species_guess=user_species_guess,
            preflight_warnings=preflight_result.get('warnings', [])
        )
        log.info(
            "CLASSIFY [step 3/5] LLM result — approved=%s confidence=%.2f species=%r "
            "condition=%r is_arthropod=%s guess_matches=%s",
            llm_result.approved, llm_result.confidence, llm_result.scientific_name,
            llm_result.condition, llm_result.is_arthropod, llm_result.user_guess_matches,
        )
        if not llm_result.approved:
            log.warning("CLASSIFY [step 3/5] LLM REJECTED — reasons: %s", llm_result.rejection_reasons)

        # Step 4: Duplicate check (only if LLM approved)
        if llm_result.approved:
            log.info("CLASSIFY [step 4/5] DUPLICATE CHECK")
            duplicate_check = self._check_for_duplicates(image_path, user_id)
            if duplicate_check['is_duplicate']:
                log.warning(
                    "CLASSIFY [step 4/5] DUPLICATE detected — %s (similarity=%.0f%%)",
                    duplicate_check['duplicate_bug_name'],
                    duplicate_check['similarity_score'] * 100,
                )
                llm_result.approved = False
                llm_result.rejection_reasons.append(
                    f"Duplicate of existing bug: {duplicate_check['duplicate_bug_name']}"
                )
                llm_result.reasoning += f"\n\nDuplicate detected: {duplicate_check['similarity_score']:.0%} similar."
            else:
                log.info("CLASSIFY [step 4/5] No duplicate found")

        # Step 5: Normalise species name via GBIF backbone (synonym resolution + fill order/family)
        if llm_result.approved:
            log.info("CLASSIFY [step 5/5] GBIF BACKBONE normalisation — input name: %r", llm_result.scientific_name)
            llm_result = self._normalize_species_via_backbone(llm_result)
            log.info(
                "CLASSIFY [step 5/5] BACKBONE done — canonical=%r order=%r family=%r",
                llm_result.scientific_name, llm_result.order, llm_result.family,
            )
        else:
            log.info("CLASSIFY [step 5/5] Skipped backbone (not approved)")

        log.info(
            "CLASSIFY FINAL — approved=%s species=%r confidence=%.2f provider=%s/%s",
            llm_result.approved, llm_result.scientific_name, llm_result.confidence,
            llm_result.llm_provider, llm_result.llm_model,
        )
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

        # Apply classifier URL override from DB settings
        try:
            from app.models import SystemSetting
            db_url = SystemSetting.get('classifier_url')
            if db_url:
                current_app.config['BUG_CLASSIFIER_URL'] = db_url
        except Exception:
            pass

        # Use PoseidonPipeline: tries /classify (ViT species-level) then /predict (genus-level)
        log = current_app.logger
        try:
            from app.services.poseidon_pipeline import PoseidonPipeline
            pipeline = PoseidonPipeline()
            caps = pipeline.capabilities()
            log.info("POSEIDON caps: %s", caps)
            preds, source = pipeline.classify(image_path)
            similar = []
            if caps.get('embed'):
                similar = pipeline.embed_and_search(image_path, top_k=5)
        except Exception as exc:
            log.warning("POSEIDON pipeline error: %s", exc)
            preds, source = [], 'none'
            similar = []

        self._poseidon_candidates = [
            {
                'scientific_name': p.scientific_name,
                'common_name': p.common_name,
                'confidence': p.confidence,
                'rank': p.rank,
                'source': source,
            }
            for p in preds[:5]
            if p.scientific_name
        ]
        self._poseidon_candidates.extend([
            {
                'scientific_name': s.scientific_name,
                'common_name': s.common_name,
                'distance': s.distance,
                'rank': 'candidate',
                'source': 'embedding',
            }
            for s in similar[:5]
            if s.scientific_name
        ])

        if not preds:
            log.info("POSEIDON returned no predictions (source=%s) — classifier unavailable or empty", source)
            if similar:
                self._poseidon_hint = {
                    'scientific_name': similar[0].scientific_name,
                    'confidence': 0.0,
                    'source': 'embedding',
                    'rank': 'candidate',
                }
                log.info(
                    "POSEIDON embedding returned %d nearest-neighbour candidates; using them as LLM hints",
                    len(similar),
                )
            try:
                from app.models import SystemSetting
                db_required = SystemSetting.get('classifier_required')
                required = (db_required == 'true') if db_required is not None else current_app.config.get('HF_BUG_CLASSIFIER_REQUIRED', False)
            except Exception:
                required = current_app.config.get('HF_BUG_CLASSIFIER_REQUIRED', False)
            if required:
                log.warning("POSEIDON classifier required but unavailable — rejecting")
                return BugClassificationResult({
                    'approved': False,
                    'confidence': 0.0,
                    'is_arthropod': False,
                    'rejection_reasons': ['Poseidon classifier unavailable'],
                    'reasoning': 'Classifier is required but could not run.',
                    'quality_assessment': 'Image quality not assessed.',
                    'llm_provider': 'poseidon',
                    'llm_model': source,
                })
            log.info("POSEIDON unavailable and not required — will fall through to LLM")
            return None

        log.info("POSEIDON %s returned %d predictions:", source, len(preds))
        for i, p in enumerate(preds[:5]):
            log.info("  [%d] %s (confidence=%.2f%%)", i + 1, p.scientific_name, p.confidence * 100)

        best = preds[0]
        label = best.scientific_name
        log.info(
            "POSEIDON best: %r @ %.2f%% (rank=%s source=%s threshold=%.0f%%)",
            label, best.confidence * 100, best.rank, source, self.min_confidence * 100,
        )

        user_guess_matches = None
        user_guess_feedback = ''
        if user_species_guess:
            user_guess_matches = (
                user_species_guess.lower() in label.lower() or
                label.lower() in user_species_guess.lower()
            )
            log.info(
                "POSEIDON guess check: user_guess=%r poseidon=%r matches=%s",
                user_species_guess, label, user_guess_matches,
            )
            if user_guess_matches:
                user_guess_feedback = f"Your guess matches the classifier prediction: {label}."
            else:
                user_guess_feedback = f"The classifier predicted {label}; your guess was noted as a hint."

        is_species_level = (
            source == 'convnext' and
            best.rank == 'species' and
            bool(re.match(r'^[A-Z][a-zA-Z-]+\s+[a-z][a-zA-Z-]+(?:\s+[a-z][a-zA-Z-]+)?$', label or ''))
        )
        if not is_species_level:
            log.info(
                "POSEIDON %s prediction is not a final species-level ID (rank=%s label=%r) — saving as hint, deferring to LLM vision",
                source, best.rank, label,
            )
            self._poseidon_hint = {
                'scientific_name': label,
                'confidence': best.confidence,
                'source': source,
                'rank': best.rank,
            }
            return None

        if best.confidence < self.min_confidence:
            log.info(
                "POSEIDON %s confidence %.2f%% < threshold %.0f%% — saving as hint, deferring to LLM",
                source, best.confidence * 100, self.min_confidence * 100,
            )
            self._poseidon_hint = {
                'scientific_name': label,
                'confidence': best.confidence,
                'source': source,
                'rank': best.rank,
            }
            return None

        if similar and not self._embedding_supports_prediction(label, similar):
            log.info(
                "POSEIDON species prediction %r was not supported by local embedding neighbours %s — "
                "saving as hint, deferring to LLM",
                label, [s.scientific_name for s in similar[:5]],
            )
            self._poseidon_hint = {
                'scientific_name': label,
                'confidence': best.confidence,
                'source': source,
                'rank': best.rank,
            }
            return None

        return BugClassificationResult({
            'approved': True,
            'confidence': best.confidence,
            'is_arthropod': True,
            'identified_species': label,
            'common_name': best.common_name or label,
            'scientific_name': label,
            'order': None,
            'family': None,
            'user_guess_matches': user_guess_matches,
            'user_guess_feedback': user_guess_feedback,
            'reasoning': f"Poseidon {source} classifier identified {label} with {best.confidence:.0%} confidence.",
            'quality_assessment': 'Accepted by Poseidon classifier.',
            'rejection_reasons': [],
            'warnings': [f"Poseidon {source}: {label} ({best.confidence:.0%})"],
            'llm_provider': 'poseidon',
            'llm_model': source,
        })

    def _embedding_supports_prediction(self, predicted_name: str, similar: list) -> bool:
        """Require exact BioCLIP/FAISS species support before auto-accepting."""
        predicted_key = self._binomial_key(predicted_name)
        if not predicted_key:
            return False
        return any(
            self._binomial_key(getattr(candidate, 'scientific_name', '')) == predicted_key
            for candidate in similar[:5]
        )

    @staticmethod
    def _binomial_key(name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        match = re.match(r'^\s*([A-Z][a-zA-Z-]+)\s+([a-z][a-zA-Z-]+)', name)
        if not match:
            return None
        return f"{match.group(1)} {match.group(2)}".lower()
    
    def _preflight_checks(self, image_path: str) -> Dict[str, Any]:
        """Fast, non-LLM checks for obvious disqualifiers"""
        log = current_app.logger
        result = {
            'passed': True,
            'issues': [],
            'warnings': []
        }

        format_check = self.quality_checker.check_format(image_path)
        if not format_check['passes']:
            result['passed'] = False
            result['issues'].append(format_check['issue'])
            log.info("PREFLIGHT format: FAIL — %s", format_check['issue'])
        else:
            log.info("PREFLIGHT format: OK")

        resolution_check = self.quality_checker.check_resolution(
            image_path, self.min_image_width, self.min_image_height
        )
        if not resolution_check['passes']:
            result['passed'] = False
            result['issues'].append(resolution_check['issue'])
            log.info("PREFLIGHT resolution: FAIL — %s", resolution_check['issue'])
        else:
            log.info("PREFLIGHT resolution: OK")

        size_check = self.quality_checker.check_file_size(
            image_path, self.max_file_size_mb
        )
        if not size_check['passes']:
            result['passed'] = False
            result['issues'].append(size_check['issue'])
            log.info("PREFLIGHT file size: FAIL — %s", size_check['issue'])
        else:
            log.info("PREFLIGHT file size: OK")

        # AI-generation heuristic: check EXIF for camera metadata.
        try:
            from PIL import Image as _PILImage
            from PIL.ExifTags import TAGS as _EXIF_TAGS
            _img = _PILImage.open(image_path)
            raw_exif = _img._getexif() if hasattr(_img, '_getexif') else None
            if raw_exif:
                exif = {_EXIF_TAGS.get(k, k): v for k, v in raw_exif.items()}
                make  = exif.get('Make', '')
                model = exif.get('Model', '')
                dt    = exif.get('DateTimeOriginal', '')
                has_camera = bool(make or model or dt)
                log.info("PREFLIGHT EXIF: make=%r model=%r date=%r has_camera=%s",
                         make, model, dt, has_camera)
            else:
                has_camera = False
                log.info("PREFLIGHT EXIF: no EXIF data found")

            if not has_camera:
                result['warnings'].append(
                    'No camera EXIF metadata found. This can happen after phone edits, web uploads, '
                    'or format conversion; treat it only as a weak AI-generation signal.'
                )
        except Exception as exc:
            log.info("PREFLIGHT EXIF: could not read EXIF — %s", exc)

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
            preflight_warnings=preflight_warnings,
            classifier_prediction=self._poseidon_hint,
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
        model = self._ensure_vision_model(self._get_preferred_model())
        log = current_app.logger
        log.info(
            "LLM CLASSIFY — provider=%s model=%s media_type=%s "
            "poseidon_hint=%s user_guess=%r",
            model.provider, model.model_name, media_type,
            (f"{self._poseidon_hint['scientific_name']} @ {self._poseidon_hint['confidence']:.0%}"
             if self._poseidon_hint else "none"),
            user_species_guess,
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

            log.info("LLM CLASSIFY raw response (%d chars): %s", len(response or ''), (response or '')[:500])

            if not response:
                raise ValueError("LLM returned empty response")

            result_data = _extract_json(response)
            result_data['llm_provider'] = model.provider
            result_data['llm_model'] = model.model_name
            result_data = self._downgrade_uncertain_taxonomy(result_data)
            log.info(
                "LLM CLASSIFY parsed — approved=%s confidence=%.2f species=%r "
                "common=%r order=%r condition=%r reasoning=%s",
                result_data.get('approved'), result_data.get('confidence', 0),
                result_data.get('identified_species'), result_data.get('common_name'),
                result_data.get('order'), result_data.get('condition'),
                (result_data.get('reasoning') or '')[:200],
            )
            if result_data.get('rejection_reasons'):
                log.info("LLM CLASSIFY rejection reasons: %s", result_data['rejection_reasons'])
            return BugClassificationResult(result_data)

        except Exception as e:
            log.warning(
                "LLM CLASSIFY failed (provider=%s model=%s) — %s: %s — falling back to manual review",
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
        log = current_app.logger
        if not result.scientific_name and not result.identified_species:
            log.info("BACKBONE skipped — no scientific name to resolve")
            return result
        name = result.scientific_name or result.identified_species
        log.info("BACKBONE querying GBIF for: %r", name)
        try:
            from app.services.taxonomy import GBIFBackbone
            match = GBIFBackbone().resolve_accepted(name)
            if not match:
                log.info("BACKBONE no GBIF match found for %r — keeping original name", name)
                return result
            canonical = match.get('canonicalName') or name
            log.info(
                "BACKBONE match — status=%s rank=%s canonical=%r "
                "order=%r family=%r gbif_confidence=%s",
                match.get('status'), match.get('rank'), canonical,
                match.get('order'), match.get('family'), match.get('confidence'),
            )
            if canonical != name:
                log.info("BACKBONE renamed: %r → %r", name, canonical)
            result.scientific_name = canonical
            if not result.order and match.get('order'):
                result.order = match['order']
            if not result.family and match.get('family'):
                result.family = match['family']
        except Exception as exc:
            log.warning("BACKBONE normalisation failed: %s", exc)
        return result
    
    def _build_classification_prompt(
        self,
        nickname: Optional[str],
        description: Optional[str],
        user_species_guess: Optional[str],
        preflight_warnings: list,
        classifier_prediction: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build classification prompt with user hint validation"""

        # Build classifier hint section (from Poseidon low-confidence prediction)
        classifier_hint_section = ""
        if classifier_prediction or self._poseidon_candidates:
            candidate_lines = []
            for c in self._poseidon_candidates[:8]:
                label = c.get('scientific_name') or ''
                common = c.get('common_name')
                rank = c.get('rank') or 'candidate'
                src_name = c.get('source') or 'classifier'
                if c.get('confidence') is not None:
                    score = f"{c['confidence']:.0%}"
                elif c.get('distance') is not None:
                    score = f"distance {c['distance']:.3f}"
                else:
                    score = "unscored"
                candidate_lines.append(
                    f"- {label}{f' ({common})' if common else ''} — {rank}, {src_name}, {score}"
                )
            candidates_text = "\n".join(candidate_lines) if candidate_lines else "- none"
            if classifier_prediction:
                name = classifier_prediction.get('scientific_name', '')
                conf = classifier_prediction.get('confidence', 0.0)
                src = classifier_prediction.get('source', 'classifier')
                primary_hint = (
                    f'The Poseidon image classifier ({src}) predicted: "{name}" at {conf:.0%} confidence.\n'
                    "This is below the auto-approval threshold. Use it as a taxonomic clue, but rely on what you see."
                )
            else:
                primary_hint = (
                    "Poseidon did not return a classifier prediction, but local embedding search returned nearest-neighbour candidates. "
                    "Use them as a shortlist only, and rely on the image evidence."
                )
            classifier_hint_section = f"""

**CLASSIFIER PRE-SCREENING (low confidence — use as context only):**
{primary_hint}

Local candidate list from classifier/embedding search:
{candidates_text}
"""

        # Build user hint section
        user_hint_section = ""
        if user_species_guess:
            user_hint_section = f"""

**USER'S SPECIES GUESS (HINT ONLY - YOU MUST VALIDATE):**
The user believes this might be: "{user_species_guess}"

⚠️ **CRITICAL VALIDATION RULES:**
1. **Independently verify** what you see in the image
2. **Cross-reference** the user's guess with visual evidence
3. **Correct the ID if the guess is wrong** (e.g., user says "bullet ant" but you see a ladybug)
4. **Accept valid arthropod photos even when the user's guess is wrong**
5. **Provide feedback** on whether the guess was accurate

**Anti-Manipulation Check:**
- If user's guess is drastically wrong (different order/family), flag it in feedback/warnings
- Users cannot change stats by misidentifying their bug
- Base your decision on WHAT YOU SEE, not what user claims
- Do not reject a clear real arthropod photo solely because the user's guess was wrong
"""

        prompt = f"""You are the FINAL AUTHORITY on bug submission classification for a bug battle arena game.

Your job: Analyze this image and determine if it should be APPROVED or REJECTED.

**Submission Context:**
{f"User's chosen name: {nickname}" if nickname else "No name provided yet"}
{f"User's description: {description}" if description else "No description provided"}
{f"Pre-flight warnings: {', '.join(preflight_warnings)}" if preflight_warnings else "No pre-flight issues"}
{classifier_hint_section}{user_hint_section}

**APPROVAL CRITERIA:**

✅ **APPROVE if:**
- Image clearly shows an arthropod (insect, arachnid, myriapod, crustacean)
- Bug is the main subject of the photo
- Image quality sufficient to identify distinguishing features
- Photo appears to be a real specimen photograph (phone camera, DSLR, macro shot)
- Confidence >= 60%
- If user provided species guess: use it only as a hint; a wrong guess should be corrected, not blindly accepted
- Dead, squashed, or damaged specimens are ALL accepted — condition is recorded and affects stats
- Imperfect photos (slight blur, harsh flash, busy background) are fine as long as the bug is identifiable

❌ **REJECT if:**
- Not an arthropod (vertebrates, mollusks, worms, etc.)
- Image is drawing, illustration, toy, or CGI
- Image appears AI-generated based on multiple visual artifacts or impossible anatomy
- Bug too small/blurry/dark to identify
- Multiple bugs (must be single specimen)
- Image quality is too poor to confirm it is a real arthropod
- Confidence < 60%

🤖 **AI IMAGE DETECTION:**
Look for these signs of AI generation and REJECT if present:
- Unnaturally perfect, uniform lighting with no shadows or harsh flash
- Background is suspiciously clean, blurred, or AI-bokeh
- Anatomically impossible features (extra legs, merged body parts, impossible symmetry)
- Texture looks "painted" or lacks the grain/noise of real photos
- Missing EXIF metadata is a weak signal only. Many real photos lose EXIF after editing, screenshots, or upload compression.
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
- Example: User says "bullet ant" but image shows "ladybug" → APPROVE as ladybug if the photo is otherwise valid; flag the mismatch in feedback/warnings
- Example: User says "beetle" but image shows "weevil" (both Coleoptera) → APPROVE + gentle correction
- Example: User says "wasp" but image shows "bee" (both Hymenoptera) → APPROVE + note difference

🔬 **TAXONOMY ACCURACY RULES:**
- Do not invent an exact species when the image only supports genus, family, or order.
- Use `scientific_name` only for a real binomial/trinomial scientific name, such as "Harmonia axyridis" or "Phidippus audax".
- If you can only identify genus/family/order, set `scientific_name` to null, put the best human-readable ID in `common_name`, and explain the uncertainty in `reasoning`.
- `confidence` should reflect how confident you are in the taxonomic level you report, not how strongly the user's guess nudged you.
- Ticks are arachnids, not insects and not spiders. They usually have an oval flattened body, compact fused-looking body regions, no narrow spider waist, and legs clustered toward the front. Common hard ticks belong to order `Ixodida`, family `Ixodidae`.
- Do not call a tick a ground spider. If the image shows a hard tick but you cannot identify species, set `scientific_name` to null and use a cautious common name such as "hard tick" or "unidentified tick".

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
- "🚨 Your guess was far off: you claimed 'bullet ant', but the image shows a ladybug. I classified it from the image instead."
- "🚨 Your guess was far off: you identified this as a 'mantis', but it appears to be an orthopteran such as a grasshopper/katydid."

**IMPORTANT:**
- You have FINAL AUTHORITY - if you reject, it's rejected
- User's guess is a HINT, not truth
- Base decision on WHAT YOU SEE in the image
- Confidence must be >= 0.60 to approve
- Prevent stat manipulation through misidentification
- Do not reject a valid real arthropod solely because the user's species guess was wrong

Analyze the image now and respond with your classification decision."""

        return prompt

    def _downgrade_uncertain_taxonomy(self, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """Avoid storing vague local-model guesses as authoritative IDs."""
        if not result_data.get('approved'):
            return result_data
        scientific = (result_data.get('scientific_name') or '').strip()
        has_binomial = bool(re.match(r'^[A-Z][a-zA-Z-]+\s+[a-z][a-zA-Z-]+(?:\s+[a-z][a-zA-Z-]+)?$', scientific))
        if has_binomial:
            return result_data

        previous = result_data.get('common_name') or result_data.get('identified_species') or result_data.get('order')
        result_data['scientific_name'] = None
        result_data['identified_species'] = None
        result_data['common_name'] = 'Unidentified arthropod'
        result_data['confidence'] = min(float(result_data.get('confidence') or 0), 0.55)
        warnings = list(result_data.get('warnings') or [])
        warnings.append(
            "The local vision model did not return a reliable scientific name, so this submission needs manual review"
            f"{f' (tentative visual label was: {previous})' if previous else ''}."
        )
        result_data['warnings'] = warnings
        reasoning = result_data.get('reasoning') or ''
        result_data['reasoning'] = (
            reasoning.rstrip() + " "
            "Because the local model did not provide a real binomial scientific name, the taxonomic label was downgraded to unidentified arthropod for manual review."
        ).strip()
        return result_data

    def _ensure_vision_model(self, model: 'LLMModel') -> 'LLMModel':
        """Avoid sending image classification to a text-only model."""
        from app.services.llm_manager import LLMModel

        log = current_app.logger
        if model.provider == 'ollama':
            caps = self.llm._get_model_caps(model.model_name)
            if not caps.get('native_vision'):
                log.warning(
                    "Vision analysis was configured for non-vision Ollama model %s; using %s instead.",
                    model.model_name, LLMModel.GEMMA4_E4B.model_name,
                )
                return LLMModel.GEMMA4_E4B

        if model.provider == 'openai' and model in {
            LLMModel.GPT_4,
            LLMModel.GPT_4_TURBO,
            LLMModel.GPT_35_TURBO,
        }:
            log.warning(
                "Vision analysis was configured for OpenAI text model %s; using %s instead.",
                model.model_name, LLMModel.GPT_4O.model_name,
            )
            return LLMModel.GPT_4O

        return model
    
    def _get_preferred_model(self) -> 'LLMModel':
        """Determine which LLM model to use"""
        from app.services.llm_manager import LLMModel, LLMConfig
        
        if self.preferred_provider:
            if self.preferred_provider == 'anthropic':
                return LLMModel.CLAUDE_SONNET_4
            elif self.preferred_provider == 'openai':
                return LLMModel.GPT_4O
            elif self.preferred_provider == 'ollama':
                return LLMModel.GEMMA4_E4B
        
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
