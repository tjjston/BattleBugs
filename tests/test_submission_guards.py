"""Tests for duplicate-image submission guards."""

import imagehash
from PIL import Image

from app import db
from app.models import Bug
from tests.conftest import create_bug, create_user


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_pattern_hash(top_color, bottom_color):
    """Return an imagehash for a 16×16 image split top/bottom by two colours."""
    img = Image.new('RGB', (16, 16), top_color)
    for y in range(8, 16):
        for x in range(16):
            img.putpixel((x, y), bottom_color)
    return imagehash.average_hash(img)


# ── Image hash duplicate detection ───────────────────────────────────────────

def test_identical_images_have_zero_hamming_distance(app):
    h1 = _make_pattern_hash((255, 0, 0), (0, 0, 255))
    h2 = _make_pattern_hash((255, 0, 0), (0, 0, 255))
    assert h1 - h2 == 0


def test_very_different_images_exceed_threshold(app):
    # Top-bright / bottom-dark  vs  top-dark / bottom-bright  → very different hashes
    h_a = _make_pattern_hash((255, 255, 255), (0, 0, 0))
    h_b = _make_pattern_hash((0, 0, 0), (255, 255, 255))
    assert h_a - h_b > 8


def test_hash_duplicate_query_finds_match(app):
    user = create_user('hashuser', 'hash@example.com')
    original_hash = _make_pattern_hash((200, 50, 50), (50, 50, 200))
    create_bug(user, image_hash=str(original_hash))

    # Nearly identical pattern
    candidate = _make_pattern_hash((200, 50, 50), (50, 50, 200))
    results = db.session.query(Bug.image_hash).filter(Bug.image_hash.isnot(None)).all()
    matches = [
        h for (h,) in results
        if imagehash.hex_to_hash(h) - candidate <= 8
    ]
    assert len(matches) == 1


def test_hash_duplicate_query_misses_distinct_image(app):
    user = create_user('hashuser2', 'hash2@example.com')
    create_bug(user, image_hash=str(_make_pattern_hash((255, 255, 255), (0, 0, 0))))

    # Inverted pattern → clearly different
    candidate = _make_pattern_hash((0, 0, 0), (255, 255, 255))
    results = db.session.query(Bug.image_hash).filter(Bug.image_hash.isnot(None)).all()
    matches = [
        h for (h,) in results
        if imagehash.hex_to_hash(h) - candidate <= 8
    ]
    assert len(matches) == 0
