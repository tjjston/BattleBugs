"""
Poseidon AI Pipeline Client
============================
Interfaces with the Poseidon inference server (BUG_CLASSIFIER_URL).

Three-tier pipeline architecture:

  Tier 1 — Detection (YOLOv8m / RT-DETR)
    POST /detect   → bounding boxes, confidence, segmentation mask
    Falls back to full-image if endpoint unavailable.

  Tier 2 — Classification (ConvNeXt-Base / ViT-B/16 fine-tuned on iNaturalist/BIOSCAN)
    POST /classify → species probabilities at species/genus/family level
    Falls back to /predict (current HF classifier endpoint).

  Tier 3 — Embedding Search (BioCLIP → FAISS)
    POST /embed    → 512-d species embedding
    GET  /similar  → nearest neighbours from FAISS index
    Falls back to taxonomy text search.

When the server only has /health + /predict, Tiers 1 and 3 are skipped
gracefully and Tier 2 uses the existing HF endpoint.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from typing import Optional

import requests
from flask import current_app


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class BoundingBox:
    x1: float; y1: float; x2: float; y2: float
    confidence: float
    label: str = 'arthropod'


@dataclass
class SpeciesPrediction:
    scientific_name: str
    common_name: Optional[str]
    confidence: float
    rank: str = 'species'       # species | genus | family
    taxon_id: Optional[int] = None


@dataclass
class SimilarSpecies:
    scientific_name: str
    common_name: Optional[str]
    distance: float             # lower = more similar
    photo_url: Optional[str] = None


@dataclass
class PipelineResult:
    # Raw inputs
    image_path: str

    # Tier 1 — detection
    detection_available: bool = False
    bounding_boxes: list[BoundingBox] = field(default_factory=list)
    detection_confidence: float = 0.0

    # Tier 2 — classification
    classification_available: bool = False
    top_predictions: list[SpeciesPrediction] = field(default_factory=list)
    best_scientific_name: Optional[str] = None
    best_confidence: float = 0.0
    classifier_source: str = 'none'     # 'hf_predict' | 'convnext' | 'vit'

    # Tier 3 — embedding search
    embedding_available: bool = False
    similar_species: list[SimilarSpecies] = field(default_factory=list)

    # Final resolved taxonomy (filled in by TaxonomyService after pipeline)
    resolved_scientific_name: Optional[str] = None
    resolved_common_name: Optional[str] = None
    resolved_gbif_key: Optional[int] = None
    taxonomy_chain: dict = field(default_factory=dict)   # order/family/genus/species

    @property
    def approved(self) -> bool:
        return self.best_confidence >= 0.45

    @property
    def primary_prediction(self) -> Optional[SpeciesPrediction]:
        return self.top_predictions[0] if self.top_predictions else None


# ── Pipeline client ───────────────────────────────────────────────────────────

class PoseidonPipeline:
    """
    Stateless client for the Poseidon inference server.
    Instantiate per-request; all methods are safe to call if server is down.
    """

    def __init__(self):
        self.base_url = current_app.config.get('BUG_CLASSIFIER_URL', 'http://192.168.0.99:8877').rstrip('/')
        self.timeout_detect   = int(current_app.config.get('POSEIDON_DETECT_TIMEOUT',   15))
        self.timeout_classify = int(current_app.config.get('POSEIDON_CLASSIFY_TIMEOUT', 30))
        self.timeout_embed    = int(current_app.config.get('POSEIDON_EMBED_TIMEOUT',    20))
        self._caps: Optional[dict] = None   # cached server capabilities

    # ── Capability discovery ──────────────────────────────────────────────────

    def capabilities(self) -> dict:
        """
        Query /health and map it to a normalised capability dict.

        Poseidon health shape:
            {"status":"ok","detect_loaded":true,"classify_loaded":true,
             "bioclip_loaded":true,"faiss_vectors":0, ...}
        Legacy HF shape:
            {"ready":true}
        """
        if self._caps is not None:
            return self._caps
        try:
            r = requests.get(f"{self.base_url}/health", timeout=5)
            if r.ok:
                data = r.json()
                is_poseidon = data.get('status') == 'ok'
                self._caps = {
                    # Poseidon keys
                    'detect':   data.get('detect_loaded',   False) if is_poseidon else False,
                    'classify': data.get('classify_loaded', False) if is_poseidon else False,
                    'embed':    data.get('bioclip_loaded',  False) if is_poseidon else False,
                    # /predict available on Poseidon whenever classify is up,
                    # and also on legacy HF servers
                    'predict':  (data.get('classify_loaded', False) if is_poseidon
                                 else data.get('ready', False)),
                }
                current_app.logger.info(
                    "POSEIDON caps: detect=%s classify=%s embed=%s predict=%s (faiss=%s vectors)",
                    self._caps['detect'], self._caps['classify'],
                    self._caps['embed'], self._caps['predict'],
                    data.get('faiss_vectors', '?'),
                )
                return self._caps
        except Exception as exc:
            current_app.logger.warning("POSEIDON /health unreachable: %s", exc)
        self._caps = {'detect': False, 'classify': False, 'embed': False, 'predict': False}
        return self._caps

    # ── Tier 1: Detection ─────────────────────────────────────────────────────

    def detect(self, image_path: str) -> list[BoundingBox]:
        """
        YOLOv8m / RT-DETR: locate and crop the bug in the image.

        Server endpoint: POST /detect
          Request:  multipart/form-data  file=<image>
          Response: [{"x1":0.1,"y1":0.2,"x2":0.8,"y2":0.9,"confidence":0.92,"label":"arthropod"}, ...]

        When unavailable: returns a single full-image pseudo-box (confidence 1.0).
        """
        caps = self.capabilities()
        if not caps.get('detect'):
            current_app.logger.debug("POSEIDON detect endpoint not available — using full-image fallback")
            return [BoundingBox(x1=0, y1=0, x2=1, y2=1, confidence=1.0)]

        try:
            with open(image_path, 'rb') as fh:
                r = requests.post(f"{self.base_url}/detect",
                                  files={'file': fh}, timeout=self.timeout_detect)
            r.raise_for_status()
            data = r.json()
            img_w = data.get('width') or 1
            img_h = data.get('height') or 1
            boxes = []
            for item in data.get('detections', []):
                boxes.append(BoundingBox(
                    x1=item['x1'] / img_w, y1=item['y1'] / img_h,
                    x2=item['x2'] / img_w, y2=item['y2'] / img_h,
                    confidence=float(item.get('confidence', 0)),
                    label=item.get('label', 'arthropod'),
                ))
            return boxes or [BoundingBox(x1=0, y1=0, x2=1, y2=1, confidence=1.0)]
        except Exception as exc:
            current_app.logger.warning("POSEIDON /detect failed: %s", exc)
            return [BoundingBox(x1=0, y1=0, x2=1, y2=1, confidence=1.0)]

    # ── Tier 2: Classification ────────────────────────────────────────────────

    def classify(self, image_path: str) -> tuple[list[SpeciesPrediction], str]:
        """
        ConvNeXt-Base / ViT-B/16 species classifier.

        Server endpoint: POST /classify
          Request:  multipart/form-data  file=<image>
          Response: [{"scientific_name":"Apis mellifera","common_name":"Western honey bee",
                      "confidence":0.87,"rank":"species","taxon_id":47219}, ...]

        Falls back to legacy /predict endpoint (HF genus classifier) if /classify is unavailable.

        Returns: (list[SpeciesPrediction], source_label)
        """
        caps = self.capabilities()

        # Preferred: full ConvNeXt/ViT species classifier
        if caps.get('classify'):
            try:
                with open(image_path, 'rb') as fh:
                    r = requests.post(f"{self.base_url}/classify",
                                      files={'file': fh}, timeout=self.timeout_classify)
                r.raise_for_status()
                preds = []
                for p in r.json().get('predictions', []):
                    label = p.get('label', '')
                    # Packed label: "{id}_{Kingdom}_{Phylum}_{Class}_{Order}_{Family}_{Genus}_{epithet}"
                    parts = label.split('_')
                    if len(parts) >= 8:
                        scientific_name = f"{parts[6]} {parts[7]}"
                    elif len(parts) >= 7:
                        scientific_name = parts[6]
                    else:
                        scientific_name = label
                    preds.append(SpeciesPrediction(
                        scientific_name=scientific_name,
                        common_name=None,
                        confidence=float(p.get('score', 0)),
                        rank='species',
                    ))
                return preds, 'convnext'
            except Exception as exc:
                current_app.logger.warning("POSEIDON /classify failed: %s", exc)

        # Fallback: legacy HF genus-level /predict endpoint
        if caps.get('predict'):
            try:
                with open(image_path, 'rb') as fh:
                    r = requests.post(f"{self.base_url}/predict",
                                      files={'file': fh}, timeout=self.timeout_classify)
                r.raise_for_status()
                raw = r.json()
                preds = [
                    SpeciesPrediction(
                        scientific_name=p.get('label', 'Unknown'),
                        common_name=None,
                        confidence=float(p.get('score', 0)),
                        rank='genus',   # HF model predicts genus, not species
                    )
                    for p in raw
                ]
                return preds, 'hf_predict'
            except Exception as exc:
                current_app.logger.warning("POSEIDON /predict failed: %s", exc)

        return [], 'none'

    # ── Tier 3: Embedding Search ──────────────────────────────────────────────

    def embed_and_search(self, image_path: str, top_k: int = 5) -> list[SimilarSpecies]:
        """
        BioCLIP embedding → FAISS nearest-neighbour search.

        Server endpoint: POST /embed
          Request:  multipart/form-data  file=<image>
          Response: {"embedding": [...512 floats...],
                     "similar": [{"scientific_name":"...","distance":0.12,"photo_url":"..."}, ...]}

        When unavailable: returns [].  The caller should fall back to iNaturalist similar_species.
        """
        caps = self.capabilities()
        if not caps.get('embed'):
            return []

        try:
            with open(image_path, 'rb') as fh:
                r = requests.post(f"{self.base_url}/embed",
                                  files={'file': fh},
                                  params={'top_k': top_k},
                                  timeout=self.timeout_embed)
            r.raise_for_status()
            data = r.json()
            return [
                SimilarSpecies(
                    scientific_name=s.get('scientific_name', s.get('label', 'Unknown')),
                    common_name=s.get('common_name'),
                    distance=float(s.get('distance', 1.0)),
                    photo_url=s.get('photo_url'),
                )
                for s in data.get('neighbors', [])
            ]
        except Exception as exc:
            current_app.logger.warning("POSEIDON /embed failed: %s", exc)
            return []

    # ── Full pipeline ─────────────────────────────────────────────────────────

    def run(self, image_path: str) -> PipelineResult:
        """
        Execute the full three-tier pipeline and return a unified PipelineResult.

        Tier 1: detect     → find bug, crop if multi-bug image
        Tier 2: classify   → species probabilities
        Tier 3: embed      → FAISS similar species

        All tiers degrade gracefully when not available.
        After this returns, call TaxonomyService.resolve_pipeline_result() to
        normalise the best prediction via GBIF backbone.
        """
        result = PipelineResult(image_path=image_path)

        # Tier 1 — Detection
        boxes = self.detect(image_path)
        result.bounding_boxes = boxes
        result.detection_available = any(b.confidence < 1.0 for b in boxes)  # True if real YOLO ran
        result.detection_confidence = max((b.confidence for b in boxes), default=0.0)

        # Tier 2 — Classification
        preds, source = self.classify(image_path)
        result.top_predictions = preds
        result.classifier_source = source
        result.classification_available = bool(preds)
        if preds:
            best = preds[0]
            result.best_scientific_name = best.scientific_name
            result.best_confidence = best.confidence

        # Tier 3 — Embedding Search
        similar = self.embed_and_search(image_path)
        result.similar_species = similar
        result.embedding_available = bool(similar)

        current_app.logger.info(
            "POSEIDON pipeline: detect=%s classify=%s(%s conf=%.2f) embed=%s",
            result.detection_available, source, result.best_scientific_name,
            result.best_confidence, result.embedding_available,
        )
        return result


# ── Taxonomy resolution hook ─────────────────────────────────────────────────

def resolve_pipeline_result(result: PipelineResult) -> PipelineResult:
    """
    After running the Poseidon pipeline, normalise the best prediction using
    the GBIF backbone and iNaturalist layer.

    Populates: resolved_scientific_name, resolved_common_name,
               resolved_gbif_key, taxonomy_chain.
    """
    if not result.best_scientific_name:
        return result

    from app.services.taxonomy import GBIFBackbone, iNaturalistLayer

    backbone = GBIFBackbone()
    match = backbone.resolve_accepted(result.best_scientific_name)
    if match:
        result.resolved_scientific_name = match.get('canonicalName') or result.best_scientific_name
        result.resolved_gbif_key = match.get('usageKey')
        result.taxonomy_chain = {k: match.get(k) for k in ('kingdom', 'phylum', 'class_', 'order', 'family', 'genus', 'species')}

        if not result.resolved_common_name:
            vern = backbone.get_vernacular_names(match['usageKey']) if match.get('usageKey') else []
            if vern:
                result.resolved_common_name = vern[0]

    if not result.resolved_common_name and result.resolved_scientific_name:
        inat = iNaturalistLayer()
        taxon = inat.search_taxon(result.resolved_scientific_name)
        if taxon:
            result.resolved_common_name = taxon.get('preferred_common_name')

    return result
