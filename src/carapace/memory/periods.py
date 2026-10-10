"""Period keys in the user's timezone.

Weeks are ISO weeks (Monday start). A week belongs to the month of its Thursday, so every week
sits in exactly one month and the month -> week -> session tree stays consistent. A session's
month follows from its week, never from its calendar date.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import DigestLevel

_WEEK_KEY = re.compile(r"(\d{4})-W(\d{2})")
_MONTH_KEY = re.compile(r"(\d{4})-(\d{2})")
_THURSDAY = 4


def week_key(at: datetime, tz: ZoneInfo) -> str:
    return week_key_for_date(at.astimezone(tz).date())


def week_key_for_date(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_start(key: str) -> date:
    """Monday of the week. Raises ValueError for malformed or nonexistent weeks (e.g. W53)."""
    match = _WEEK_KEY.fullmatch(key)
    if match is None:
        raise ValueError(f"invalid week key {key!r}, expected e.g. '2026-W36'")
    return date.fromisocalendar(int(match[1]), int(match[2]), 1)


def month_key_for_week(key: str) -> str:
    thursday = week_start(key) + timedelta(days=_THURSDAY - 1)
    return f"{thursday.year}-{thursday.month:02d}"


def month_weeks(key: str) -> list[str]:
    """Week keys belonging to the month, in order."""
    first = _month_first_day(key)
    # The month's first Thursday falls in its first week.
    thursday = first + timedelta(days=(_THURSDAY - first.isoweekday()) % 7)
    weeks = []
    while thursday.month == first.month:
        weeks.append(week_key_for_date(thursday))
        thursday += timedelta(weeks=1)
    return weeks


def period_weeks(key: str) -> list[str]:
    """Weeks of a week key (itself) or month key, for filters that take either."""
    if _WEEK_KEY.fullmatch(key):
        week_start(key)
        return [key]
    return month_weeks(key)


def period_dates(level: DigestLevel, key: str) -> tuple[date, date]:
    """First and last day (inclusive). A month spans its weeks, not the calendar month."""
    match level:
        case DigestLevel.week:
            start = week_start(key)
            return start, start + timedelta(days=6)
        case DigestLevel.month:
            weeks = month_weeks(key)
            return week_start(weeks[0]), week_start(weeks[-1]) + timedelta(days=6)


def period_ended(level: DigestLevel, key: str, now: datetime, tz: ZoneInfo) -> bool:
    return now.astimezone(tz).date() > period_dates(level, key)[1]


def local_midnight_utc(day: date, tz: ZoneInfo) -> datetime:
    """Start of *day* in *tz*, as UTC.

    ponytail: zones whose DST switch skips midnight (rare, e.g. historic America/Santiago) get
    zoneinfo's fold-0 reading of the nonexistent 00:00, an hour off. Good enough for windows.
    """
    return datetime.combine(day, time(), tzinfo=tz).astimezone(UTC)


def _month_first_day(key: str) -> date:
    match = _MONTH_KEY.fullmatch(key)
    if match is None or not 1 <= int(match[2]) <= 12:
        raise ValueError(f"invalid month key {key!r}, expected e.g. '2026-09'")
    return date(int(match[1]), int(match[2]), 1)
