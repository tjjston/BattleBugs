"""
Arena News Briefing Service
Gathers recent activity and generates an LLM sports-announcer-style briefing.
Persists to a shared file cache so all Gunicorn workers share the same result.
Generation is non-blocking — the homepage never waits on the LLM.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta

from app import db
from app.models import Battle, Bug, BugAchievement, Comment, BugLore, Tournament

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_CACHE_FILE = os.path.join(_PROJECT_ROOT, 'database', 'news_cache.json')

_in_memory: dict = {}
_bg_lock = threading.Lock()
_generating = False
CACHE_TTL = 3600


def _read_cache() -> tuple[str | None, float]:
    m = _in_memory.get('text')
    m_at = float(_in_memory.get('at', 0))
    if m and (time.time() - m_at) < CACHE_TTL:
        return m, m_at
    try:
        with open(_CACHE_FILE) as f:
            d = json.load(f)
        return d.get('text'), float(d.get('at', 0))
    except Exception:
        return None, 0.0


def _write_cache(text: str) -> None:
    _in_memory['text'] = text
    _in_memory['at'] = time.time()
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        tmp = _CACHE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'text': text, 'at': time.time()}, f)
        os.replace(tmp, _CACHE_FILE)
    except Exception:
        pass


def get_current_season() -> dict:
    now = datetime.now(timezone.utc)
    month = now.month
    year = now.year
    if month in (12, 1, 2):
        name, icon = 'Winter', '❄️'
    elif month in (3, 4, 5):
        name, icon = 'Spring', '🌸'
    elif month in (6, 7, 8):
        name, icon = 'Summer', '☀️'
    else:
        name, icon = 'Autumn', '🍂'
    return {'name': name, 'icon': icon, 'year': year, 'label': f'{icon} {name} {year}'}


def get_recent_activity(days: int = 7) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    recent_battles = (
        Battle.query
        .filter(Battle.battle_date >= cutoff)
        .order_by(Battle.battle_date.desc())
        .limit(20).all()
    )
    new_bugs = (
        Bug.query
        .filter(Bug.submission_date >= cutoff)
        .order_by(Bug.submission_date.desc())
        .limit(10).all()
    )
    new_retirements = (
        Bug.query
        .filter(Bug.is_retired == True, Bug.retired_at >= cutoff)
        .order_by(Bug.retired_at.desc()).all()
    )
    new_achievements = (
        BugAchievement.query
        .filter(BugAchievement.earned_date >= cutoff)
        .order_by(BugAchievement.earned_date.desc())
        .limit(15).all()
    )
    completed_tournaments = (
        Tournament.query
        .filter(Tournament.status == 'completed', Tournament.end_date >= cutoff)
        .order_by(Tournament.end_date.desc()).all()
    )
    new_lore = (
        BugLore.query
        .filter(BugLore.created_at >= cutoff)
        .order_by(BugLore.created_at.desc())
        .limit(5).all()
    )
    new_comments = (
        Comment.query
        .filter(Comment.created_at >= cutoff)
        .order_by(Comment.created_at.desc())
        .limit(5).all()
    )
    return {
        'battles': recent_battles,
        'new_bugs': new_bugs,
        'new_retirements': new_retirements,
        'new_achievements': new_achievements,
        'new_species': [b for b in new_bugs if b.species_id],
        'completed_tournaments': completed_tournaments,
        'new_lore': new_lore,
        'new_comments': new_comments,
        'days': days,
    }


def _build_activity_summary(activity: dict) -> str:
    lines = [f"Recent activity in the Bug Arena over the last {activity['days']} days:"]

    battles = activity['battles']
    if battles:
        lines.append(f"\nBATTLES ({len(battles)} total):")
        for b in battles[:8]:
            winner = b.winner.nickname if b.winner else 'Draw'
            lines.append(f"  {b.bug1.nickname} vs {b.bug2.nickname} — Winner: {winner} ({b.battle_date.strftime('%b %d')})")

    retirements = activity['new_retirements']
    if retirements:
        lines.append(f"\nRETIREMENTS:")
        for bug in retirements:
            lines.append(f"  {bug.nickname} ({bug.wins}W-{bug.losses}L) has been retired to legend status.")

    new_bugs = activity['new_bugs']
    if new_bugs:
        lines.append(f"\nNEW ENTRANTS ({len(new_bugs)}):")
        for bug in new_bugs[:5]:
            species = bug.common_name or bug.scientific_name or 'unknown species'
            lines.append(f"  {bug.nickname} ({species}) submitted by {bug.owner.username}")

    tournaments = activity['completed_tournaments']
    if tournaments:
        lines.append(f"\nTOURNAMENT RESULTS:")
        for t in tournaments:
            champ = t.winner.nickname if t.winner else 'TBD'
            lines.append(f"  {t.name} — Champion: {champ}")

    achievements = activity['new_achievements']
    rare = [a for a in achievements if a.rarity in ('rare', 'uncommon')]
    if rare:
        lines.append(f"\nNOTABLE ACHIEVEMENTS:")
        for a in rare[:5]:
            lines.append(f"  {a.bug.nickname} earned '{a.achievement_name}' ({a.rarity})")

    if activity['new_lore']:
        lines.append(f"\nCOMMUNITY LORE ADDED: {len(activity['new_lore'])} new entries")

    return '\n'.join(lines)


def generate_news_briefing(activity: dict) -> str:
    from flask import current_app

    context = _build_activity_summary(activity)
    if not any([activity['battles'], activity['new_bugs'], activity['new_retirements'],
                activity['completed_tournaments']]):
        return "The arena is quiet… but the bugs are always training. Stay tuned for the next bout!"

    try:
        from app.services.llm_manager import LLMService
        llm = LLMService()
        system = (
            "You are the official announcer of the Bug Arena — a gladiatorial combat league for insects. "
            "Write a punchy, exciting news briefing in the style of a sports highlight reel. "
            "Use dramatic language, give bugs personality, celebrate victories and retirements. "
            "Keep it under 200 words. No headers, just flowing prose. No markdown."
        )
        prompt = f"{context}\n\nWrite the arena news briefing for this period. Be dramatic and exciting!"
        return llm.generate(prompt, task='battle_narrative', system_prompt=system, max_tokens=300)
    except Exception as exc:
        current_app.logger.warning("News briefing LLM failed: %s", exc)
        return _plain_fallback(activity)


def _plain_fallback(activity: dict) -> str:
    parts = []
    b = activity['battles']
    if b:
        parts.append(f"{len(b)} battles shook the arena this week.")
        top = [x for x in b if x.winner]
        if top:
            w = top[0].winner.nickname
            opp = top[0].bug1.nickname if top[0].bug2.nickname == w else top[0].bug2.nickname
            parts.append(f"{w} dominated in a standout fight against {opp}.")
    for bug in activity['new_retirements']:
        parts.append(f"Arena legend {bug.nickname} has retired with {bug.wins} wins — a true champion.")
    for bug in activity['new_bugs'][:2]:
        parts.append(f"New challenger {bug.nickname} has entered the arena!")
    for t in activity['completed_tournaments']:
        champ = t.winner.nickname if t.winner else 'unknown'
        parts.append(f"{t.name} concluded — {champ} takes the crown!")
    return ' '.join(parts) if parts else "The arena awaits its next battle…"


def _generate_in_background(app, cache_file: str) -> None:
    global _generating
    try:
        with app.app_context():
            activity = get_recent_activity(days=7)
            text = generate_news_briefing(activity)
            _write_cache(text)
    except Exception:
        pass
    finally:
        _generating = False


def get_cached_briefing() -> str:
    global _generating
    now = time.time()

    cached_text, cached_at = _read_cache()
    if cached_text and (now - cached_at) < CACHE_TTL:
        return cached_text

    # Nothing fresh — kick off background generation (non-blocking)
    with _bg_lock:
        if not _generating:
            _generating = True
            from flask import current_app
            app = current_app._get_current_object()
            threading.Thread(
                target=_generate_in_background,
                args=(app, _CACHE_FILE),
                daemon=True,
            ).start()

    # Return stale data if any, else placeholder until generation finishes
    return cached_text or "The arena scoreboard is refreshing — check back in a moment!"


def invalidate_news_cache() -> None:
    _in_memory.clear()
    try:
        os.remove(_CACHE_FILE)
    except OSError:
        pass
