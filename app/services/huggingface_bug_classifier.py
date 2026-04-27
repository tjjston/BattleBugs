from dataclasses import dataclass
from typing import Optional

from flask import current_app


@dataclass
class HuggingFaceBugPrediction:
    available: bool
    approved: bool
    confidence: float
    label: Optional[str] = None
    error: Optional[str] = None
    raw_predictions: Optional[list] = None


class HuggingFaceBugClassifier:
    """REST-based bug image classifier — calls the local API at BUG_CLASSIFIER_URL."""

    def __init__(self):
        self.base_url = current_app.config.get("BUG_CLASSIFIER_URL", "http://192.168.0.99:8082").rstrip("/")
        self.min_confidence = float(current_app.config.get("HF_BUG_CLASSIFIER_MIN_CONFIDENCE", 0.45))

    def _check_health(self) -> bool:
        import requests
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=3)
            return resp.ok and resp.json().get("ready", False)
        except Exception:
            return False

    def classify(self, image_path: str) -> HuggingFaceBugPrediction:
        import requests

        if not self._check_health():
            return HuggingFaceBugPrediction(
                available=False, approved=False, confidence=0.0,
                error="Bug classifier API is not reachable",
            )

        try:
            with open(image_path, "rb") as fh:
                resp = requests.post(
                    f"{self.base_url}/predict",
                    files={"file": fh},
                    timeout=30,
                )
            resp.raise_for_status()
            predictions = resp.json()
        except Exception as exc:
            current_app.logger.warning("Bug classifier REST call failed: %s", exc)
            return HuggingFaceBugPrediction(
                available=True, approved=False, confidence=0.0, error=str(exc),
            )

        if not predictions:
            return HuggingFaceBugPrediction(
                available=True, approved=False, confidence=0.0,
                error="No predictions returned", raw_predictions=[],
            )

        best = predictions[0]
        confidence = float(best.get("score", 0.0))
        label = str(best.get("label", "")).strip()
        approved = confidence >= self.min_confidence
        return HuggingFaceBugPrediction(
            available=True,
            approved=approved,
            confidence=confidence,
            label=label,
            raw_predictions=predictions,
            error=None if approved else "Prediction confidence below threshold",
        )
