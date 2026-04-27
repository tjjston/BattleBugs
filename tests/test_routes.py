from app import db
from app.models import Job
from app.services.job_queue import VISUAL_LORE_JOB
from tests.conftest import create_bug


def test_bug_profile_shows_enrichment_state(client, user):
    bug = create_bug(user, enrichment_status='pending')
    job = Job(type=VISUAL_LORE_JOB, status='queued')
    job.payload = {'bug_id': bug.id}
    db.session.add(job)
    db.session.commit()

    response = client.get(f'/bug/{bug.id}')

    assert response.status_code == 200
    assert b'Enrichment' in response.data
    assert b'pending' in response.data


def test_submit_bug_page_includes_tutorial(client, user):
    from tests.conftest import login

    login(client, user.username)
    response = client.get('/bug/submit')

    assert response.status_code == 200
    assert b'Open Submission Tutorial' in response.data
    assert b'Armored Beetle' in response.data


def test_generate_name_falls_back_when_llm_fails(client, user, monkeypatch):
    from tests.conftest import login

    login(client, user.username)
    monkeypatch.setattr(
        "app.services.llm_manager.LLMService.generate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("model unavailable")),
    )

    response = client.post('/api/bug/generate', json={'field': 'nickname', 'context': {'common_name': 'beetle'}})

    assert response.status_code == 200
    data = response.get_json()
    assert data['fallback'] is True
    assert data['suggestions']
