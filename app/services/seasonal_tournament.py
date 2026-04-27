"""
Seasonal Tournament Manager
Auto-creates one flagship tournament per calendar season (Spring / Summer / Autumn / Winter).
Called once per day by the APScheduler; idempotent — safe to call at any time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import Optional

# Season definitions: name → (months, icon, label, start_month_of_season)
# start_month = first calendar month of the season; tournament_month = month the event starts
_SEASONS: dict[str, dict] = {
    'spring': {'icon': '🌸', 'months': (3, 4, 5),  'tournament_month': 4},
    'summer': {'icon': '☀️', 'months': (6, 7, 8),  'tournament_month': 7},
    'autumn': {'icon': '🍂', 'months': (9, 10, 11), 'tournament_month': 10},
    'winter': {'icon': '❄️', 'months': (12, 1, 2),  'tournament_month': 1},
}


def get_season_for_date(dt: Optional[datetime] = None) -> tuple[str, int]:
    """Return (season_name, season_year) for the given date.

    season_year is the year of December (or the current year for Spring/Summer/Autumn),
    so winter that starts Dec 2025 has season_year=2025.
    """
    if dt is None:
        dt = datetime.utcnow()
    month = dt.month
    year = dt.year
    for name, meta in _SEASONS.items():
        if month in meta['months']:
            if name == 'winter' and month in (1, 2):
                # Jan/Feb belong to the PREVIOUS December's winter
                return name, year - 1
            return name, year
    return 'spring', year  # fallback


def get_season_key(dt: Optional[datetime] = None) -> str:
    """Return a stable string key like 'spring_2026'."""
    name, year = get_season_for_date(dt)
    return f'{name}_{year}'


def _tournament_start_date(season_name: str, season_year: int) -> date:
    """Return the canonical start date for the season's tournament."""
    meta = _SEASONS[season_name]
    t_month = meta['tournament_month']
    # For winter, tournament_month=1 belongs to season_year+1
    if season_name == 'winter':
        t_year = season_year + 1
    else:
        t_year = season_year
    return date(t_year, t_month, 1)


def ensure_seasonal_tournament() -> Optional[object]:
    """Create the current season's flagship tournament if it doesn't exist yet.

    Returns the Tournament if newly created, None if it already existed.
    Should be called inside an app context.
    """
    from app import db
    from app.models import Tournament

    now = datetime.utcnow()
    season_name, season_year = get_season_for_date(now)
    key = f'{season_name}_{season_year}'

    existing = Tournament.query.filter_by(season_key=key).first()
    if existing:
        return None  # Already created for this season

    meta = _SEASONS[season_name]
    start = _tournament_start_date(season_name, season_year)
    start_dt = datetime(start.year, start.month, start.day)

    # Registration closes 14 days before the tournament starts, but at least today+1
    reg_deadline_dt = start_dt - timedelta(days=14)
    if reg_deadline_dt <= now:
        reg_deadline_dt = now + timedelta(days=1)

    # If the tournament start is already past, push it forward appropriately
    if start_dt <= now:
        start_dt = now + timedelta(days=7)
        reg_deadline_dt = now + timedelta(days=1)

    name = f"{meta['icon']} {season_name.capitalize()} {season_year} Championship"
    tournament = Tournament(
        name=name,
        start_date=start_dt,
        registration_deadline=reg_deadline_dt,
        status='registration',
        max_participants=16,
        season_key=key,
    )
    db.session.add(tournament)
    db.session.commit()
    return tournament


def get_active_seasonal_tournament() -> Optional[object]:
    """Return the current season's tournament, or None."""
    from app.models import Tournament
    key = get_season_key()
    return Tournament.query.filter_by(season_key=key).first()
