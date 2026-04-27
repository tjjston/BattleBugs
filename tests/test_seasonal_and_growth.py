"""Tests for Feature 7 (seasonal tournaments) and Feature 10 (stat growth)."""
from datetime import datetime, timedelta

from app import db
from app.models import Bug, Tournament
from app.services.seasonal_tournament import (
    get_season_for_date,
    get_season_key,
    ensure_seasonal_tournament,
    get_active_seasonal_tournament,
)
from app.services.achievements import award_battle_achievements, _apply_stat_growth
from tests.conftest import create_bug, create_user


# ── Feature 7: Seasonal Tournaments ──────────────────────────────────────────

def test_get_season_for_date_spring(app):
    assert get_season_for_date(datetime(2026, 4, 15)) == ('spring', 2026)


def test_get_season_for_date_winter_december(app):
    assert get_season_for_date(datetime(2025, 12, 1)) == ('winter', 2025)


def test_get_season_for_date_winter_january(app):
    # January 2026 belongs to winter_2025
    assert get_season_for_date(datetime(2026, 1, 10)) == ('winter', 2025)


def test_get_season_key_format(app):
    key = get_season_key(datetime(2026, 4, 15))
    assert key == 'spring_2026'


def test_ensure_seasonal_tournament_creates_one(app):
    t = ensure_seasonal_tournament()
    assert t is not None
    assert t.season_key is not None
    assert t.status == 'registration'
    assert t.max_participants == 16


def test_ensure_seasonal_tournament_is_idempotent(app):
    t1 = ensure_seasonal_tournament()
    t2 = ensure_seasonal_tournament()
    assert t2 is None  # second call returns None (already exists)
    assert Tournament.query.count() == 1


def test_get_active_seasonal_tournament_finds_created(app):
    ensure_seasonal_tournament()
    t = get_active_seasonal_tournament()
    assert t is not None
    assert t.season_key == get_season_key()


def test_ensure_seasonal_tournament_has_valid_dates(app):
    t = ensure_seasonal_tournament()
    assert t.start_date > datetime.utcnow()
    if t.registration_deadline:
        assert t.registration_deadline < t.start_date


# ── Feature 10: Stat Growth ───────────────────────────────────────────────────

def test_stat_growth_applies_correctly(app):
    user = create_user('growthuser', 'growth@example.com')
    bug = create_bug(user, speed=50)
    original_speed = bug.speed

    _apply_stat_growth(bug, stat='speed', amount=2)
    db.session.commit()

    refreshed = db.session.get(Bug, bug.id)
    assert refreshed.speed == original_speed + 2
    assert refreshed.stat_growth == 2


def test_stat_growth_capped_at_100(app):
    user = create_user('capuser', 'cap@example.com')
    bug = create_bug(user, attack=99)

    _apply_stat_growth(bug, stat='attack', amount=5)
    db.session.commit()

    refreshed = db.session.get(Bug, bug.id)
    assert refreshed.attack == 100
    assert refreshed.stat_growth == 1  # only 1 point actually applied


def test_three_win_milestone_boosts_speed(app):
    user = create_user('milestone3', 'ms3@example.com')
    winner = create_bug(user, speed=60, wins=3)
    original_speed = winner.speed

    award_battle_achievements(winner)
    db.session.commit()

    refreshed = db.session.get(Bug, winner.id)
    assert refreshed.speed == original_speed + 2


def test_five_win_milestone_boosts_defense(app):
    user = create_user('milestone5', 'ms5@example.com')
    winner = create_bug(user, defense=60, wins=5)
    original_defense = winner.defense

    award_battle_achievements(winner)
    db.session.commit()

    refreshed = db.session.get(Bug, winner.id)
    assert refreshed.defense == original_defense + 2


def test_stat_growth_not_applied_twice_for_same_milestone(app):
    user = create_user('nomulti', 'nomulti@example.com')
    winner = create_bug(user, speed=60, wins=3)
    original_speed = winner.speed

    award_battle_achievements(winner)
    award_battle_achievements(winner)
    db.session.commit()

    refreshed = db.session.get(Bug, winner.id)
    # Achievement deduplication ensures growth only applied once
    assert refreshed.speed == original_speed + 2
