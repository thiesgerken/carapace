from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from carapace.memory.models import DigestLevel
from carapace.memory.periods import (
    local_midnight_utc,
    month_key_for_week,
    month_weeks,
    period_dates,
    period_ended,
    period_weeks,
    week_key,
    week_key_for_date,
    week_start,
)

BERLIN = ZoneInfo("Europe/Berlin")


def test_week_key_uses_user_timezone():
    # Sunday 23:30 UTC is already Monday in Berlin.
    at = datetime(2026, 8, 30, 23, 30, tzinfo=UTC)
    assert week_key(at, UTC) == "2026-W35"
    assert week_key(at, BERLIN) == "2026-W36"


@pytest.mark.parametrize(
    ("day", "key"),
    [
        (date(2026, 12, 31), "2026-W53"),  # 2026 starts on a Thursday, so it has 53 weeks
        (date(2027, 1, 3), "2026-W53"),  # early January can belong to the previous ISO year
        (date(2027, 1, 4), "2027-W01"),
        (date(2024, 12, 30), "2025-W01"),  # late December can belong to the next ISO year
    ],
)
def test_iso_week_year_boundaries(day: date, key: str):
    assert week_key_for_date(day) == key


@pytest.mark.parametrize(
    ("week", "month"),
    [
        ("2026-W36", "2026-09"),  # Aug 31 to Sep 6: Thursday Sep 3
        ("2026-W40", "2026-10"),  # Sep 28 to Oct 4: Thursday Oct 1
        ("2026-W53", "2026-12"),  # Thursday Dec 31
        ("2025-W01", "2025-01"),  # Dec 30 2024 to Jan 5 2025: Thursday Jan 2
    ],
)
def test_week_belongs_to_month_of_its_thursday(week: str, month: str):
    assert month_key_for_week(week) == month


def test_month_weeks():
    assert month_weeks("2026-09") == ["2026-W36", "2026-W37", "2026-W38", "2026-W39"]
    assert month_weeks("2026-12") == ["2026-W49", "2026-W50", "2026-W51", "2026-W52", "2026-W53"]
    assert month_weeks("2025-01") == ["2025-W01", "2025-W02", "2025-W03", "2025-W04", "2025-W05"]


def test_every_week_sits_in_exactly_one_month():
    months = [f"{year}-{month:02d}" for year in (2025, 2026, 2027) for month in range(1, 13)]
    counts = Counter(week for month in months for week in month_weeks(month))
    for week, count in counts.items():
        assert count == 1, week
        assert month_weeks(month_key_for_week(week)).count(week) == 1
    # Every ISO week of 2026 (all 53) is covered.
    assert {f"2026-W{n:02d}" for n in range(1, 54)} <= counts.keys()


@pytest.mark.parametrize("key", ["2025-W53", "2026-W00", "2026-W5", "2026-09", "26-W01"])
def test_invalid_week_keys(key: str):
    with pytest.raises(ValueError):
        week_start(key)


@pytest.mark.parametrize("key", ["2026-13", "2026-00", "2026-9", "2026-W36x"])
def test_invalid_month_keys(key: str):
    with pytest.raises(ValueError):
        month_weeks(key)


def test_period_dates():
    assert period_dates(DigestLevel.week, "2026-W36") == (date(2026, 8, 31), date(2026, 9, 6))
    # A month spans its weeks, not the calendar month.
    assert period_dates(DigestLevel.month, "2026-09") == (date(2026, 8, 31), date(2026, 9, 27))


def test_period_ended_in_user_timezone():
    sunday_late = datetime(2026, 9, 6, 21, 30, tzinfo=UTC)  # 23:30 in Berlin
    assert not period_ended(DigestLevel.week, "2026-W36", sunday_late, BERLIN)
    assert period_ended(DigestLevel.week, "2026-W36", sunday_late + timedelta(hours=1), BERLIN)
    assert period_ended(DigestLevel.week, "2026-W36", sunday_late, ZoneInfo("Asia/Tokyo"))


def test_local_midnight_across_dst():
    # Berlin switches to summer time on 2026-03-29.
    assert local_midnight_utc(date(2026, 3, 29), BERLIN) == datetime(2026, 3, 28, 23, tzinfo=UTC)
    assert local_midnight_utc(date(2026, 3, 30), BERLIN) == datetime(2026, 3, 29, 22, tzinfo=UTC)
    # And back on 2026-10-25.
    assert local_midnight_utc(date(2026, 10, 26), BERLIN) == datetime(2026, 10, 25, 23, tzinfo=UTC)


def test_period_weeks():
    assert period_weeks("2026-W36") == ["2026-W36"]
    assert period_weeks("2026-09") == month_weeks("2026-09")
    with pytest.raises(ValueError):
        period_weeks("2025-W53")
