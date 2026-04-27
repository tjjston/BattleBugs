from app import db
from app.models import Bug
from tests.conftest import create_bug, login


def test_assign_flair_requires_login(client, user):
    bug = create_bug(user)
    response = client.post(f'/api/bug/{bug.id}/assign-flair', json={'flair': 'Champion'})
    assert response.status_code == 302


def test_assign_flair_requires_bug_owner_or_moderator(client, user, other_user):
    bug = create_bug(user)
    login(client, other_user.username)

    response = client.post(f'/api/bug/{bug.id}/assign-flair', json={'flair': 'Champion'})

    assert response.status_code == 403


def test_owner_can_assign_flair(client, user):
    bug = create_bug(user)
    login(client, user.username)

    response = client.post(f'/api/bug/{bug.id}/assign-flair', json={'flair': 'Champion'})

    assert response.status_code == 200
    assert response.get_json()['flair'] == 'Champion'
    assert db.session.get(Bug, bug.id).flair == 'Champion'


def test_moderation_approve_requires_moderator(client, user):
    bug = create_bug(user, requires_manual_review=True)
    login(client, user.username)

    response = client.post(f'/admin/bug/{bug.id}/approve')

    assert response.status_code == 403


def test_moderator_can_approve_bug(client, user, moderator):
    bug = create_bug(user, requires_manual_review=True)
    login(client, moderator.username)

    response = client.post(f'/admin/bug/{bug.id}/approve')

    assert response.status_code == 302
    updated = db.session.get(Bug, bug.id)
    assert updated.requires_manual_review is False
    assert updated.is_verified is True


def test_db_explorer_disabled_by_default(client, admin):
    login(client, admin.username)

    response = client.get('/admin/db-explorer')

    assert response.status_code == 302
