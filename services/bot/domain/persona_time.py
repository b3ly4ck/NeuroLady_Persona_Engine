"""Persona-time — the daily-versioned identity clock (F-006 FR-006-24 / NFR-006-14).

The persona's age is **derived from her birthdate at the current local date** ("28 years and 3
days"), not a stored integer, so the identity prompt is naturally versioned per local day. Pure and
deterministic: same birthdate + same date ⇒ same output.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def today_in_tz(tz_name: str) -> date:
    """Her current local calendar date (drives persona-time). Falls back to UTC on a bad tz."""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 - unknown/garbled tz → UTC (never crash the turn)
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def _last_birthday(birthdate: date, on: date) -> tuple[int, date]:
    """Return (completed_years, date_of_the_most_recent_birthday_on_or_before `on`).

    Handles a Feb-29 birthdate in a non-leap year by rolling to Feb 28 (so age still advances).
    """
    years = on.year - birthdate.year
    if (on.month, on.day) < (birthdate.month, birthdate.day):
        years -= 1
    target_year = birthdate.year + years
    try:
        anniversary = birthdate.replace(year=target_year)
    except ValueError:  # Feb 29 → non-leap year
        anniversary = date(target_year, 2, 28)
    return years, anniversary


def age_years_days(birthdate: date, on: date) -> tuple[int, int]:
    """(years, days) since `birthdate` as of `on`. On the birthday days == 0."""
    years, anniversary = _last_birthday(birthdate, on)
    days = (on - anniversary).days
    return years, days


def age_phrase(birthdate: date, on: date) -> str:
    """Human phrase like 'a 28-year-old woman (28 years and 3 days today)'."""
    years, days = age_years_days(birthdate, on)
    day_word = "day" if days == 1 else "days"
    return f"{years} years and {days} {day_word}"
