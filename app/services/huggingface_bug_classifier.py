from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from flask import current_app


@dataclass
class HuggingFaceBugPrediction:
    available: bool
    approved: bool
    confidence: float
    label: Optional[str] = None
    error: Optional[str] = None
    raw_predictions: Optional[list[dict]] = None


@lru_cache(maxsize=1)
def _load_pipeline(model_name: str):
    from transformers import pipeline

    return pipeline("image-classification", model=model_name)


class HuggingFaceBugClassifier:
    """Local Hugging Face image classifier for bug submission pre-approval."""

    def __init__(self):
        self.model_name = current_app.config.get("HF_BUG_CLASSIFIER_MODEL", "ph0masta/bug_classifier")
        self.min_confidence = float(current_app.config.get("HF_BUG_CLASSIFIER_MIN_CONFIDENCE", 0.45))
        self.top_k = int(current_app.config.get("HF_BUG_CLASSIFIER_TOP_K", 5))

    def classify(self, image_path: str) -> HuggingFaceBugPrediction:
        try:
            classifier = _load_pipeline(self.model_name)
            predictions = classifier(image_path, top_k=self.top_k)
        except ImportError as exc:
            current_app.logger.warning("Hugging Face classifier dependencies are missing: %s", exc)
            return HuggingFaceBugPrediction(available=False, approved=False, confidence=0.0, error=str(exc))
        except Exception as exc:
            current_app.logger.warning("Hugging Face bug classifier failed: %s", exc)
            return HuggingFaceBugPrediction(available=False, approved=False, confidence=0.0, error=str(exc))

        if not predictions:
            return HuggingFaceBugPrediction(
                available=True,
                approved=False,
                confidence=0.0,
                error="No predictions returned",
                raw_predictions=[],
            )

        best = predictions[0]
        confidence = float(best.get("score", 0.0))
        label = str(best.get("label", "")).strip()
        return HuggingFaceBugPrediction(
            available=True,
            approved=confidence >= self.min_confidence,
            confidence=confidence,
            label=label,
            raw_predictions=predictions,
            error=None if confidence >= self.min_confidence else "Prediction confidence below threshold",
        )
