"""
Seasonal Tournament Manager
Auto-creates one flagship tournament per calendar season (Spring / Summer / Autumn / Winter).
Called once per day by the APScheduler; idempotent — safe to call at any time.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
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
        dt = datetime.now(timezone.utc)
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


def get_season_date_range(season_name: str, season_year: int) -> tuple[datetime, datetime]:
    """Return (start, end) datetimes for a season.

    Winter_YYYY spans Dec YYYY – Feb YYYY+1.
    """
    import calendar as _cal
    bounds = {
        'spring': (3, 5),
        'summer': (6, 8),
        'autumn': (9, 11),
        'winter': (12, 2),
    }
    start_month, end_month = bounds[season_name]
    if season_name == 'winter':
        start = datetime(season_year, 12, 1)
        end_year = season_year + 1
        last_day = _cal.monthrange(end_year, 2)[1]
        end = datetime(end_year, 2, last_day, 23, 59, 59)
    else:
        start = datetime(season_year, start_month, 1)
        last_day = _cal.monthrange(season_year, end_month)[1]
        end = datetime(season_year, end_month, last_day, 23, 59, 59)
    return start, end


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

    _now_aware = datetime.now(timezone.utc)
    now = _now_aware.replace(tzinfo=None)  # naive for DB comparisons
    season_name, season_year = get_season_for_date(_now_aware)
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


# Competitive tiers to auto-create each season (ascending power order)
_AUTO_TIERS = ['nu', 'ru', 'uu', 'ou']

# Season schedule relative to season start
_REG_DURATION_WEEKS = 2
_REGULAR_SEASON_WEEKS = 10
_TOURNAMENT_WEEKS = 1


def auto_create_seasonal_cohort(dt: Optional[datetime] = None) -> list:
    """Create one Season per competitive tier for the current calendar season.

    Idempotent — skips any tier that already has a Season for this period.
    Returns a list of newly-created Season objects.

    Schedule per season:
      - Registration:     2 weeks
      - Regular season:  10 weeks (automated daily matches)
      - Tournament:       1 week  (round-robin, auto-scheduled)
    """
    from datetime import timedelta as _td
    from app import db
    from app.models import Season

    _now_aware = dt or datetime.now(timezone.utc)
    now = _now_aware.replace(tzinfo=None) if getattr(_now_aware, 'tzinfo', None) else _now_aware
    season_name, season_year = get_season_for_date(_now_aware)
    season_start, _ = get_season_date_range(season_name, season_year)

    # Use the actual season start, but never in the past by more than we want
    reg_opens = max(season_start, now.replace(hour=0, minute=0, second=0, microsecond=0))
    reg_closes = reg_opens + _td(weeks=_REG_DURATION_WEEKS)
    rs_start = reg_closes
    rs_end = rs_start + _td(weeks=_REGULAR_SEASON_WEEKS)
    t_start = rs_end
    t_end = t_start + _td(weeks=_TOURNAMENT_WEEKS)

    meta = _SEASONS[season_name]
    icon = meta['icon']
    created = []

    for tier in _AUTO_TIERS:
        season_key = f"{season_name}_{season_year}_{tier}"
        if Season.query.filter_by(season_key=season_key).first():
            continue  # already exists

        season = Season(
            name=f"{icon} {season_name.capitalize()} {season_year} — {tier.upper()}",
            tier=tier,
            season_key=season_key,
            phase='registration',
            registration_opens=reg_opens,
            registration_closes=reg_closes,
            regular_season_start=rs_start,
            regular_season_end=rs_end,
            tournament_start=t_start,
            tournament_end=t_end,
            max_registrations=64,
        )
        db.session.add(season)
        created.append(season)

    if created:
        db.session.commit()

    return created
