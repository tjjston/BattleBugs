from datetime import datetime, timezone
from typing import Optional

from flask import current_app
from sqlalchemy import func

from app import db
from app.models import Bug, Job


VISUAL_LORE_JOB = 'visual_lore_enrichment'
TAXONOMY_JOB = 'taxonomy_enrichment'
STAT_RECALC_JOB = 'stat_recalculation'
MAX_JOB_ATTEMPTS = 3


def enqueue_job(job_type: str, payload: dict) -> Job:
    job = Job(type=job_type, status='queued')
    job.payload = payload
    db.session.add(job)
    db.session.commit()
    return job


def enqueue_bug_enrichment(bug: Bug, image_path: Optional[str] = None) -> list[Job]:
    bug.enrichment_status = 'pending'
    bug.enrichment_error = None
    db.session.add(bug)
    db.session.flush()

    jobs = [
        Job(type=VISUAL_LORE_JOB, status='queued'),
        Job(type=TAXONOMY_JOB, status='queued'),
        Job(type=STAT_RECALC_JOB, status='queued'),
    ]
    for job in jobs:
        job.payload = {'bug_id': bug.id, 'image_path': image_path or bug.image_path}
        db.session.add(job)

    db.session.commit()
    return jobs


def process_next_job() -> Optional[Job]:
    job = Job.query.filter_by(status='queued').order_by(Job.created_at.asc()).first()
    if not job:
        return None
    return process_job(job)


def process_job(job: Job) -> Job:
    job.status = 'processing'
    job.started_at = datetime.now(timezone.utc)
    job.attempts = (job.attempts or 0) + 1
    job.error = None
    db.session.commit()

    try:
        result = _dispatch_job(job)
        job.result = result or {}
        job.status = 'complete'
        job.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        current_app.logger.exception("Background job %s failed", job.id)
        job.status = 'dead' if job.attempts >= MAX_JOB_ATTEMPTS else 'failed'
        job.error = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        _mark_bug_enrichment_failed(job, str(exc))

    db.session.commit()
    _refresh_bug_enrichment_status(job)
    return job


def retry_job(job_id: int) -> Job:
    job = db.get_or_404(Job, job_id)
    job.status = 'queued'
    job.error = None
    job.attempts = 0
    job.started_at = None
    job.completed_at = None
    db.session.commit()
    return job


def _dispatch_job(job: Job) -> dict:
    if job.type == VISUAL_LORE_JOB:
        return _run_visual_lore_job(job)
    if job.type == TAXONOMY_JOB:
        return _run_taxonomy_job(job)
    if job.type == STAT_RECALC_JOB:
        return _run_stat_recalculation_job(job)
    raise ValueError(f'Unknown job type: {job.type}')


def _bug_from_job(job: Job) -> Bug:
    bug_id = job.payload.get('bug_id')
    if not bug_id:
        raise ValueError('Job payload missing bug_id')
    return db.get_or_404(Bug, bug_id)


def _run_visual_lore_job(job: Job) -> dict:
    import os as _os
    bug = _bug_from_job(job)
    image_path = job.payload.get('image_path') or bug.image_path
    if not image_path.startswith('/'):
        image_path = f"{current_app.config['UPLOAD_FOLDER']}/{image_path}"

    current_app.logger.info(
        "JOB visual_lore #%s — bug#%s image_path=%s exists=%s",
        job.id, bug.id, image_path, _os.path.exists(image_path),
    )
    if not _os.path.exists(image_path):
        upload_dir = current_app.config['UPLOAD_FOLDER']
        on_disk = _os.listdir(upload_dir) if _os.path.isdir(upload_dir) else []
        current_app.logger.error(
            "JOB visual_lore #%s — image missing at %s. "
            "UPLOAD_FOLDER=%s. Files matching bug#%s owner: %s",
            job.id, image_path, upload_dir,
            bug.id,
            [f for f in on_disk if f.startswith(f"{bug.user_id}_")],
        )
        raise FileNotFoundError(f"Bug image not found: {image_path}")

    bug.enrichment_status = 'processing'
    db.session.add(bug)
    db.session.commit()

    from app.services.visual_lore_generator import VisualLoreAnalyzer

    analyzer = VisualLoreAnalyzer()
    analyzer.apply_visual_lore_to_bug(bug, image_path)
    return {'bug_id': bug.id, 'visual_lore': 'complete'}


def _run_taxonomy_job(job: Job) -> dict:
    bug = _bug_from_job(job)
    if not bug.scientific_name:
        return {'bug_id': bug.id, 'taxonomy': 'skipped'}

    from app.services.taxonomy import TaxonomyService

    taxonomy = TaxonomyService()
    species = taxonomy.get_species_details(scientific_name=bug.scientific_name)
    if species:
        bug.species_id = species.id
        bug.common_name = bug.common_name or species.common_name
        bug.scientific_name = bug.scientific_name or species.scientific_name
        db.session.add(bug)
        db.session.commit()
        return {'bug_id': bug.id, 'taxonomy': 'linked', 'species_id': species.id}
    return {'bug_id': bug.id, 'taxonomy': 'not_found'}


def _run_stat_recalculation_job(job: Job) -> dict:
    """Background recalculation — defers to LLMStatGenerator.regenerate_stats_for_bug
    so we pick up species-baseline normalization, visual observations,
    stats_reasoning persistence, and ability_slug resolution (rather than
    re-implementing a partial copy of that flow)."""
    bug = _bug_from_job(job)
    from app.services.tier_system import LLMStatGenerator

    generator = LLMStatGenerator()
    bug = generator.regenerate_stats_for_bug(bug)
    bug.stats_generation_method = 'llm_recalc_job'
    db.session.add(bug)
    db.session.commit()
    return {
        'bug_id': bug.id,
        'stats': {
            'attack': bug.attack, 'defense': bug.defense, 'speed': bug.speed,
            'lethality': bug.lethality, 'grip': bug.grip, 'cunning': bug.cunning,
        },
    }


def _mark_bug_enrichment_failed(job: Job, error: str) -> None:
    bug_id = job.payload.get('bug_id')
    if not bug_id:
        return
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return
    bug.enrichment_status = 'failed'
    bug.enrichment_error = error
    db.session.add(bug)


def _refresh_bug_enrichment_status(job: Job) -> None:
    bug_id = job.payload.get('bug_id')
    if not bug_id:
        return
    bug = db.session.get(Bug, bug_id)
    if not bug:
        return

    related = Job.query.filter(
        func.json_extract(Job.payload_json, '$.bug_id') == bug_id
    ).all()
    if any(j.status == 'failed' for j in related):
        bug.enrichment_status = 'failed'
        bug.enrichment_error = next((j.error for j in related if j.status == 'failed'), None)
    elif related and all(j.status == 'complete' for j in related):
        bug.enrichment_status = 'complete'
        bug.enrichment_error = None
    elif any(j.status == 'processing' for j in related):
        bug.enrichment_status = 'processing'
    else:
        bug.enrichment_status = 'pending'
    db.session.add(bug)
    db.session.commit()


def start_scheduler(app) -> None:
    if not app.config.get('ENABLE_BACKGROUND_JOBS', True):
        return
    if getattr(app, '_battlebugs_scheduler_started', False):
        return

    import logging as _logging
    from apscheduler.schedulers.background import BackgroundScheduler

    # Suppress "skipped: maximum running instances" spam — this fires every
    # poll interval while an LLM job is running and fills logs with noise.
    _logging.getLogger('apscheduler.executors.default').setLevel(_logging.WARNING)
    _logging.getLogger('apscheduler.scheduler').setLevel(_logging.ERROR)

    scheduler = BackgroundScheduler(daemon=True)

    def tick():
        with app.app_context():
            process_next_job()

    scheduler.add_job(
        tick,
        'interval',
        seconds=app.config.get('JOB_POLL_INTERVAL_SECONDS', 15),
        id='battlebugs_job_worker',
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.start()
    app._battlebugs_scheduler_started = True
    app._battlebugs_scheduler = scheduler
