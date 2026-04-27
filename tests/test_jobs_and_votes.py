from app import db
from app.models import BugLore, Comment, Job
from app.services.job_queue import MAX_JOB_ATTEMPTS, TAXONOMY_JOB, enqueue_job, process_next_job, retry_job
from tests.conftest import create_bug, login


def test_taxonomy_job_without_species_is_skipped(app, user):
    bug = create_bug(user, scientific_name=None)
    enqueue_job(TAXONOMY_JOB, {'bug_id': bug.id})

    processed = process_next_job()

    assert processed.status == 'complete'
    assert processed.result['taxonomy'] == 'skipped'


def test_failed_job_can_be_retried(app):
    job = enqueue_job('unknown', {})
    process_next_job()

    failed = db.session.get(Job, job.id)
    assert failed.status == 'failed'

    retry_job(job.id)
    retried = db.session.get(Job, job.id)
    assert retried.status == 'queued'
    assert retried.error is None


def test_job_exhausted_attempts_becomes_dead(app):
    job = enqueue_job('unknown', {})
    for _ in range(MAX_JOB_ATTEMPTS):
        job.status = 'queued'
        db.session.commit()
        process_next_job()
    assert db.session.get(Job, job.id).status == 'dead'


def test_retry_job_resets_attempts(app):
    job = enqueue_job('unknown', {})
    process_next_job()
    retry_job(job.id)
    requeued = db.session.get(Job, job.id)
    assert requeued.status == 'queued'
    assert requeued.attempts == 0


def test_comment_upvote_is_idempotent(client, user, other_user):
    bug = create_bug(user)
    comment = Comment(text='Nice bug', bug_id=bug.id, user_id=user.id)
    db.session.add(comment)
    db.session.commit()
    login(client, other_user.username)

    first = client.post(f'/comment/{comment.id}/upvote')
    second = client.post(f'/comment/{comment.id}/upvote')

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()['already_voted'] is True
    assert db.session.get(Comment, comment.id).upvotes == 1


def test_lore_upvote_is_idempotent(client, user, other_user):
    bug = create_bug(user)
    lore = BugLore(lore_text='Legendary', bug_id=bug.id, user_id=user.id)
    db.session.add(lore)
    db.session.commit()
    login(client, other_user.username)

    client.post(f'/lore/{lore.id}/upvote')
    response = client.post(f'/lore/{lore.id}/upvote')

    assert response.get_json()['already_voted'] is True
    assert db.session.get(BugLore, lore.id).upvotes == 1
