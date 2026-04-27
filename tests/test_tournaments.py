from datetime import datetime, timedelta

from app import db
from app.models import Tournament, TournamentApplication, TournamentMatch
from app.services.tournament_system import TournamentEligibilityChecker, TournamentManager
from tests.conftest import create_bug, login


def test_tournament_eligibility_accepts_valid_bug(app, user):
    bug = create_bug(user, tier='ou', stats_generated=True)
    tournament = Tournament(
        name='Open',
        start_date=datetime.utcnow() + timedelta(days=7),
        created_at=datetime.utcnow() + timedelta(seconds=1),
        status='registration',
        tier='ou',
    )
    db.session.add(tournament)
    db.session.commit()

    result = TournamentEligibilityChecker.check_eligibility(bug, tournament)

    assert result['eligible'] is True


def test_apply_to_tournament_auto_approves_eligible_bug(app, user):
    bug = create_bug(user, tier='ou', stats_generated=True)
    tournament = TournamentManager.create_tournament(
        name='Open',
        start_date=datetime.utcnow() + timedelta(days=7),
        tier_restriction='ou',
        created_by_id=user.id,
    )

    application = TournamentManager.apply_to_tournament(bug.id, tournament.id, user.id)

    assert application.status == 'approved'
    assert TournamentApplication.query.count() == 1


def test_create_tournament_route_rejects_deadline_after_start(client, moderator):
    login(client, moderator.username)
    response = client.post('/tournament/create', data={
        'name': 'Bad Timing',
        'start_date': '2030-01-10',
        'registration_deadline': '2030-01-20',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert Tournament.query.filter_by(name='Bad Timing').count() == 0


def test_create_tournament_route_rejects_too_few_participants(client, moderator):
    login(client, moderator.username)
    response = client.post('/tournament/create', data={
        'name': 'Solo Event',
        'start_date': '2030-01-10',
        'max_participants': '1',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert Tournament.query.filter_by(name='Solo Event').count() == 0


def test_generate_bracket_creates_matches_and_activates_tournament(app, user):
    bugs = [create_bug(user, nickname=f'Bug {idx}', attack=10 + idx, tier='ou') for idx in range(4)]
    tournament = TournamentManager.create_tournament(
        name='Bracket',
        start_date=datetime.utcnow() + timedelta(days=7),
        tier_restriction='ou',
        created_by_id=user.id,
    )
    for bug in bugs:
        TournamentManager.apply_to_tournament(bug.id, tournament.id, user.id)

    matches = TournamentManager.generate_bracket(tournament.id)

    assert len(matches) == 2
    assert TournamentMatch.query.filter_by(tournament_id=tournament.id).count() == 3
    assert db.session.get(Tournament, tournament.id).status == 'active'
