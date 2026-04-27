from app import db
from app.models import CurrencyTransaction
from app.services.achievements import award_battle_achievements, award_submission_achievements
from app.services.economy import STAT_REGENERATION_COST
from tests.conftest import create_bug, login


def test_submission_awards_accolade_points(user):
    bug = create_bug(user)

    award_submission_achievements(bug)
    db.session.commit()

    assert user.accolade_points > 0
    assert CurrencyTransaction.query.filter_by(user_id=user.id, reason='approved_bug_submission').count() == 1


def test_achievement_points_only_awarded_once(user):
    bug = create_bug(user, wins=1)

    award_battle_achievements(bug)
    award_battle_achievements(bug)
    db.session.commit()

    assert CurrencyTransaction.query.filter_by(user_id=user.id, reason='achievement:first_win').count() == 1


def test_player_stat_recalc_confirm_spends_points(client, user):
    bug = create_bug(user)
    user.accolade_points = STAT_REGENERATION_COST
    db.session.commit()
    login(client, user.username)

    response = client.post(
        f'/bug/{bug.id}/recalc/confirm',
        data={
            'attack': 12,
            'defense': 11,
            'speed': 10,
            'special_ability': 'Reroll',
            'tier': 'ou',
        },
    )

    assert response.status_code == 302
    assert user.accolade_points == 0
    assert CurrencyTransaction.query.filter_by(user_id=user.id, reason='stat_regeneration').count() == 1


def test_player_stat_recalc_confirm_requires_points(client, user):
    bug = create_bug(user)
    user.accolade_points = STAT_REGENERATION_COST - 1
    db.session.commit()
    login(client, user.username)

    response = client.post(
        f'/bug/{bug.id}/recalc/confirm',
        data={
            'attack': 12,
            'defense': 11,
            'speed': 10,
            'special_ability': 'Reroll',
            'tier': 'ou',
        },
    )

    assert response.status_code == 302
    assert user.accolade_points == STAT_REGENERATION_COST - 1
    assert CurrencyTransaction.query.filter_by(user_id=user.id, reason='stat_regeneration').count() == 0


def test_moderator_recalc_for_other_user_does_not_spend_points(client, user, moderator):
    bug = create_bug(user)
    moderator.accolade_points = 0
    db.session.commit()
    login(client, moderator.username)

    response = client.post(
        f'/bug/{bug.id}/recalc/confirm',
        data={
            'attack': 12,
            'defense': 11,
            'speed': 10,
            'special_ability': 'Staff Edit',
            'tier': 'ou',
        },
    )

    assert response.status_code == 302
    assert moderator.accolade_points == 0
    assert CurrencyTransaction.query.filter_by(user_id=moderator.id, reason='stat_regeneration').count() == 0
