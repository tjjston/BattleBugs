from pathlib import Path

from PIL import Image

from app.services.bug_classifier import BugClassificationResult, classify_bug_submission
from app.services.poseidon_pipeline import SimilarSpecies, SpeciesPrediction


def make_image(path: Path):
    Image.new("RGB", (500, 500), color=(40, 100, 50)).save(path)


class FakePoseidonPipeline:
    def __init__(self, predictions=None, source="convnext", similar=None):
        self.predictions = predictions or []
        self.source = source
        self.similar = similar or []

    def capabilities(self):
        return {
            "detect": False,
            "classify": self.source == "convnext",
            "embed": bool(self.similar),
            "predict": True,
        }

    def classify(self, _image_path):
        return self.predictions, self.source

    def embed_and_search(self, _image_path, top_k=5):
        return self.similar[:top_k]


def test_poseidon_classifier_approves_confident_species(app, user, tmp_path, monkeypatch):
    image_path = tmp_path / "bug.jpg"
    make_image(image_path)

    predictions = [
        SpeciesPrediction(
            scientific_name="Phidippus audax",
            common_name="bold jumping spider",
            confidence=0.88,
            rank="species",
        )
    ]
    monkeypatch.setattr(
        "app.services.poseidon_pipeline.PoseidonPipeline",
        lambda: FakePoseidonPipeline(predictions, source="convnext"),
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._check_for_duplicates",
        lambda _self, _path, _user_id: {"is_duplicate": False},
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._normalize_species_via_backbone",
        lambda _self, result: result,
    )

    result = classify_bug_submission(str(image_path), user.id, user_species_guess="jumping spider")

    assert result.approved is True
    assert result.llm_provider == "poseidon"
    assert result.common_name == "bold jumping spider"
    assert result.scientific_name == "Phidippus audax"
    assert result.confidence == 0.88


def test_poseidon_low_confidence_defers_to_llm(app, user, tmp_path, monkeypatch):
    """Low Poseidon confidence should pass through to the LLM, not hard-reject."""
    image_path = tmp_path / "not_bug.jpg"
    make_image(image_path)

    predictions = [
        SpeciesPrediction(
            scientific_name="Phidippus audax",
            common_name=None,
            confidence=0.12,
            rank="species",
        )
    ]
    monkeypatch.setattr(
        "app.services.poseidon_pipeline.PoseidonPipeline",
        lambda: FakePoseidonPipeline(predictions, source="convnext"),
    )
    # Stub the LLM so it rejects cleanly (no network needed)
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._llm_comprehensive_analysis",
        lambda _self, **_kwargs: BugClassificationResult({
            "approved": False,
            "confidence": 0.2,
            "is_arthropod": False,
            "rejection_reasons": ["not a bug"],
            "llm_provider": "ollama",
            "llm_model": "stub",
        }),
    )

    result = classify_bug_submission(str(image_path), user.id)

    # The low-confidence Poseidon result is discarded; LLM made the call.
    assert result.llm_provider == "ollama"


def test_poseidon_embedding_mismatch_defers_to_llm(app, user, tmp_path, monkeypatch):
    """When FAISS has candidates, an unsupported species prediction stays a hint."""
    image_path = tmp_path / "bug.jpg"
    make_image(image_path)

    predictions = [
        SpeciesPrediction(
            scientific_name="Phidippus audax",
            common_name=None,
            confidence=0.91,
            rank="species",
        )
    ]
    similar = [
        SimilarSpecies(
            scientific_name="Harmonia axyridis",
            common_name="Asian lady beetle",
            distance=0.12,
        )
    ]
    monkeypatch.setattr(
        "app.services.poseidon_pipeline.PoseidonPipeline",
        lambda: FakePoseidonPipeline(predictions, source="convnext", similar=similar),
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._llm_comprehensive_analysis",
        lambda _self, **_kwargs: BugClassificationResult({
            "approved": True,
            "confidence": 0.7,
            "is_arthropod": True,
            "common_name": "unidentified arthropod",
            "rejection_reasons": [],
            "reasoning": "fallback",
            "llm_provider": "ollama",
            "llm_model": "stub",
        }),
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._check_for_duplicates",
        lambda _self, _path, _user_id: {"is_duplicate": False},
    )

    result = classify_bug_submission(str(image_path), user.id)

    assert result.approved is True
    assert result.llm_provider == "ollama"


def test_poseidon_genus_prediction_defers_to_llm(app, user, tmp_path, monkeypatch):
    """Genus-level fallback predictions are hints, not final species IDs."""
    image_path = tmp_path / "bug.jpg"
    make_image(image_path)

    predictions = [
        SpeciesPrediction(
            scientific_name="Phidippus",
            common_name=None,
            confidence=0.95,
            rank="genus",
        )
    ]
    monkeypatch.setattr(
        "app.services.poseidon_pipeline.PoseidonPipeline",
        lambda: FakePoseidonPipeline(predictions, source="hf_predict"),
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._llm_comprehensive_analysis",
        lambda _self, **_kwargs: BugClassificationResult({
            "approved": True,
            "confidence": 0.72,
            "is_arthropod": True,
            "common_name": "jumping spider",
            "scientific_name": "Phidippus audax",
            "identified_species": "Phidippus audax",
            "rejection_reasons": [],
            "reasoning": "fallback",
            "llm_provider": "ollama",
            "llm_model": "stub",
        }),
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._check_for_duplicates",
        lambda _self, _path, _user_id: {"is_duplicate": False},
    )
    monkeypatch.setattr(
        "app.services.bug_classifier.LLMBugClassifier._normalize_species_via_backbone",
        lambda _self, result: result,
    )

    result = classify_bug_submission(str(image_path), user.id)

    assert result.approved is True
    assert result.llm_provider == "ollama"
    assert result.scientific_name == "Phidippus audax"
