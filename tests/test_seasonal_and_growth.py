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


def test_three_win_milestone_boosts_counter_to_loser_dominant_stat(app):
    user = create_user('milestone3', 'ms3@example.com')
    winner = create_bug(user, defense=50, wins=3)
    # Loser is dominant in attack → winner should gain defense
    loser = create_bug(user, nickname='Loser', attack=90, defense=30, speed=30)
    original_defense = winner.defense

    award_battle_achievements(winner, loser=loser)
    db.session.commit()

    refreshed = db.session.get(Bug, winner.id)
    assert refreshed.defense == original_defense + 2
    assert refreshed.stat_growth == 2


def test_five_win_milestone_boosts_attack_against_defensive_loser(app):
    from app.models import BugAchievement
    user = create_user('milestone5', 'ms5@example.com')
    winner = create_bug(user, attack=50, wins=5)
    # Pre-award the 3-win achievement so only the 5-win fires here
    db.session.add(BugAchievement(bug_id=winner.id, achievement_type='three_wins',
                                   achievement_name='Arena Regular', achievement_icon='🥉', rarity='uncommon'))
    db.session.commit()
    # Loser is dominant in defense → winner should gain attack
    loser = create_bug(user, nickname='Tank', attack=30, defense=90, speed=30)
    original_attack = winner.attack

    award_battle_achievements(winner, loser=loser)
    db.session.commit()

    refreshed = db.session.get(Bug, winner.id)
    assert refreshed.attack == original_attack + 2


def test_stat_growth_not_applied_twice_for_same_milestone(app):
    user = create_user('nomulti', 'nomulti@example.com')
    winner = create_bug(user, wins=3)
    loser = create_bug(user, nickname='Loser', attack=90, defense=30, speed=30)

    before = winner.attack + winner.defense + winner.speed
    award_battle_achievements(winner, loser=loser)
    award_battle_achievements(winner, loser=loser)
    db.session.commit()

    refreshed = db.session.get(Bug, winner.id)
    # Achievement deduplication ensures growth only applied once (+2 total)
    after = refreshed.attack + refreshed.defense + refreshed.speed
    assert after == before + 2
