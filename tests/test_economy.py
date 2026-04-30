from unittest.mock import patch
from app import db
from app.models import CurrencyTransaction
from app.services.achievements import award_battle_achievements, award_submission_achievements
from tests.conftest import create_bug, login

_MOCK_STATS = {
    'attack': 60, 'defense': 55, 'speed': 70,
    'lethality': 50, 'grip': 50, 'cunning': 50,
    'special_ability': 'Mock Power', 'reasoning': 'test',
    'attack_type': 'piercing', 'defense_type': 'hard_shell',
    'size_category': 'small', 'tier_recommendation': 'uu', 'confidence': 0.9,
}


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


def test_admin_can_recalc_stats(client, admin):
    """Admin POST to /bug/<id>/recalc auto-applies stats without review step."""
    bug = create_bug(admin)
    login(client, admin.username)

    with patch('app.services.tier_system.LLMStatGenerator.generate_stats_with_llm', return_value=_MOCK_STATS):
        response = client.post(f'/bug/{bug.id}/recalc')

    assert response.status_code == 302
    db.session.refresh(bug)
    assert bug.attack == 60


def test_regular_user_cannot_recalc_stats(client, user):
    """Regular users get a 302 redirect with an error flash — not a 200 review page."""
    bug = create_bug(user)
    login(client, user.username)

    response = client.post(f'/bug/{bug.id}/recalc', follow_redirects=True)
    assert response.status_code == 200
    assert b'Only admins' in response.data or b'403' in response.data or b'permission' in response.data.lower()


def test_moderator_cannot_recalc_stats(client, user, moderator):
    """Moderators are also blocked from recalculating stats."""
    bug = create_bug(user)
    login(client, moderator.username)

    response = client.post(f'/bug/{bug.id}/recalc', follow_redirects=True)
    assert response.status_code == 200
    assert b'Only admins' in response.data or b'permission' in response.data.lower()
