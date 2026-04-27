"""Tests for duplicate-image and season/species uniqueness submission guards."""
from datetime import datetime

import imagehash
from PIL import Image

from app import db
from app.models import Bug, Species
from app.services.seasonal_tournament import get_season_for_date, get_season_date_range
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


# ── Season/species uniqueness ─────────────────────────────────────────────────

def test_season_species_uniqueness_query_finds_active_duplicate(app):
    user = create_user('sequser', 'seq@example.com')
    species = Species(scientific_name='Testus bugus', common_name='Test Bug', data_source='test')
    db.session.add(species)
    db.session.commit()

    season_name, season_year = get_season_for_date()
    season_start, season_end = get_season_date_range(season_name, season_year)
    mid_season = datetime(
        season_start.year, season_start.month,
        (season_start.day + season_end.day) // 2 or 1,
    )

    existing = Bug(
        nickname='Existing', image_path='e.jpg', user_id=user.id,
        species_id=species.id, submission_date=mid_season,
        attack=10, defense=10, speed=10,
    )
    db.session.add(existing)
    db.session.commit()

    found = Bug.query.filter(
        Bug.user_id == user.id,
        Bug.species_id == species.id,
        Bug.is_retired.isnot(True),
        Bug.submission_date.between(season_start, season_end),
    ).first()
    assert found is not None
    assert found.id == existing.id


def test_season_species_uniqueness_allows_different_species(app):
    user = create_user('sequser2', 'seq2@example.com')
    sp1 = Species(scientific_name='Buggus alpha', common_name='Alpha', data_source='test')
    sp2 = Species(scientific_name='Buggus beta', common_name='Beta', data_source='test')
    db.session.add_all([sp1, sp2])
    db.session.commit()

    season_name, season_year = get_season_for_date()
    season_start, season_end = get_season_date_range(season_name, season_year)

    existing = Bug(
        nickname='Alpha Bug', image_path='a.jpg', user_id=user.id,
        species_id=sp1.id,
        submission_date=datetime(season_start.year, season_start.month, 15),
        attack=10, defense=10, speed=10,
    )
    db.session.add(existing)
    db.session.commit()

    found = Bug.query.filter(
        Bug.user_id == user.id,
        Bug.species_id == sp2.id,  # different species
        Bug.is_retired.isnot(True),
        Bug.submission_date.between(season_start, season_end),
    ).first()
    assert found is None


def test_season_species_uniqueness_allows_retired_bug(app):
    user = create_user('retuser', 'ret@example.com')
    species = Species(scientific_name='Retiredus bugus', common_name='Retired', data_source='test')
    db.session.add(species)
    db.session.commit()

    season_name, season_year = get_season_for_date()
    season_start, season_end = get_season_date_range(season_name, season_year)

    retired_bug = Bug(
        nickname='Old Bug', image_path='r.jpg', user_id=user.id,
        species_id=species.id, is_retired=True,
        submission_date=datetime(season_start.year, season_start.month, 5),
        attack=10, defense=10, speed=10,
    )
    db.session.add(retired_bug)
    db.session.commit()

    # Retired bug should NOT block a new submission
    found = Bug.query.filter(
        Bug.user_id == user.id,
        Bug.species_id == species.id,
        Bug.is_retired.isnot(True),
        Bug.submission_date.between(season_start, season_end),
    ).first()
    assert found is None
