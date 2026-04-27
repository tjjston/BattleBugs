from pathlib import Path

from PIL import Image

from app.services.bug_classifier import classify_bug_submission
from app.services.huggingface_bug_classifier import HuggingFaceBugPrediction


def make_image(path: Path):
    Image.new("RGB", (500, 500), color=(40, 100, 50)).save(path)


def test_huggingface_classifier_approves_confident_bug(app, user, tmp_path, monkeypatch):
    image_path = tmp_path / "bug.jpg"
    make_image(image_path)

    monkeypatch.setattr(
        "app.services.huggingface_bug_classifier.HuggingFaceBugClassifier.classify",
        lambda _self, _path: HuggingFaceBugPrediction(
            available=True,
            approved=True,
            confidence=0.88,
            label="Phidippus",
            raw_predictions=[],
        ),
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._check_for_duplicates",
        lambda _self, _path, _user_id: {"is_duplicate": False},
    )

    result = classify_bug_submission(str(image_path), user.id, user_species_guess="jumping spider")

    assert result.approved is True
    assert result.llm_provider == "huggingface"
    assert result.common_name == "Phidippus"
    assert result.confidence == 0.88


def test_huggingface_classifier_rejects_low_confidence(app, user, tmp_path, monkeypatch):
    image_path = tmp_path / "not_bug.jpg"
    make_image(image_path)

    monkeypatch.setattr(
        "app.services.huggingface_bug_classifier.HuggingFaceBugClassifier.classify",
        lambda _self, _path: HuggingFaceBugPrediction(
            available=True,
            approved=False,
            confidence=0.12,
            label="Phidippus",
            error="Prediction confidence below threshold",
            raw_predictions=[],
        ),
    )

    result = classify_bug_submission(str(image_path), user.id)

    assert result.approved is False
    assert result.llm_provider == "huggingface"
    assert "confidence too low" in result.rejection_reasons[0]


def test_huggingface_unavailable_falls_back_to_llm_when_not_required(app, user, tmp_path, monkeypatch):
    image_path = tmp_path / "bug.jpg"
    make_image(image_path)

    monkeypatch.setattr(
        "app.services.huggingface_bug_classifier.HuggingFaceBugClassifier.classify",
        lambda _self, _path: HuggingFaceBugPrediction(
            available=False,
            approved=False,
            confidence=0.0,
            error="missing transformers",
        ),
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._llm_comprehensive_analysis",
        lambda _self, **_kwargs: type("Result", (), {
            "approved": True,
            "rejection_reasons": [],
            "reasoning": "fallback",
        })(),
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._check_for_duplicates",
        lambda _self, _path, _user_id: {"is_duplicate": False},
    )

    result = classify_bug_submission(str(image_path), user.id)

    assert result.approved is True
