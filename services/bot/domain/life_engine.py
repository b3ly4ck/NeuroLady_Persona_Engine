"""F-006 Life Engine — the deterministic core (pure, config-driven, no I/O).

Owns the parts of "her own living" that don't need an LLM call: deriving her **current activity**
from the free-text daily plan + the current time (FR-006-03/04), deciding **when** compression is
due (FR-006-07), and **timezone-correct scheduling** of morning/end-of-day jobs (FR-006-16,
NFR-006-07, DST-safe via the stdlib `zoneinfo`). Everything is driven by `LifeEngineConfig`
(FR-006-19/NFR-006-11) — the compression ratios, schedule hours, and prompt versions are tunables,
not hard-coded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class LifeEngineConfig:
    """All tunables (configurable without code changes — FR-006-19 / NFR-006-11)."""
    morning_hour: int = 8            # local hour the Planner runs (FR-006-01/16)
    end_of_day_hour: int = 23        # local hour the Reflector runs (FR-006-05/16)
    daily_per_week: int = 7          # FR-006-07
    weekly_per_month: int = 4
    monthly_per_year: int = 12
    years_per_epoch: int = 5
    plan_prompt_version: str = "plan_day_v1"      # FR-006-19
    reflect_prompt_version: str = "reflect_day_v1"
    compress_prompt_version: str = "compress_v1"
    goals_prompt_version: str = "update_goals_v1"


DEFAULT_CONFIG = LifeEngineConfig()

# Compression pyramid order (lowest → highest, mirrors architecture.md §4.5).
SCOPES = ("day", "week", "month", "year", "epoch")


# ── timezone-correct scheduling (FR-006-16, NFR-006-07) ─────────────────────────────────────────


def local_now(tz_name: str, now_utc: datetime) -> datetime:
    """The persona's current local time, DST-correct, from her `PERSONA.timezone`."""
    return now_utc.astimezone(ZoneInfo(tz_name))


def local_date_key(tz_name: str, now_utc: datetime) -> str:
    """Her current local calendar date, as the `YYYY-MM-DD` key used for `DAILY_PLAN`/`REFLECTION`."""
    return local_now(tz_name, now_utc).date().isoformat()


def is_local_morning(tz_name: str, now_utc: datetime, cfg: LifeEngineConfig = DEFAULT_CONFIG) -> bool:
    """True during her local morning hour — when the Planner is due (FR-006-01/16)."""
    return local_now(tz_name, now_utc).hour == cfg.morning_hour


def is_local_end_of_day(
    tz_name: str, now_utc: datetime, cfg: LifeEngineConfig = DEFAULT_CONFIG
) -> bool:
    """True during her local end-of-day hour — when the Reflector is due (FR-006-05/16)."""
    return local_now(tz_name, now_utc).hour == cfg.end_of_day_hour


# ── current activity: parse the free-text plan against the current time (FR-006-03/04) ─────────

# Matches "7:00", "07:00", "9:00-18:00", "9:00–18:00" (en/em dash), each side optionally followed
# by "AM"/"PM" (the LLM freely writes either 24h or 12h times), then optional " — "/" - "/":"
# before the activity description.
_TIME_RANGE_RE = re.compile(
    r"(?P<h1>\d{1,2}):(?P<m1>\d{2})\s*(?P<ap1>[AaPp]\.?[Mm]\.?)?"
    r"(?:\s*[-–]\s*(?P<h2>\d{1,2}):(?P<m2>\d{2})\s*(?P<ap2>[AaPp]\.?[Mm]\.?)?)?"
    r"\s*[-—:]?\s*"
)


def _to_24h(hour: int, ampm: str | None) -> int:
    """Normalize a possibly-12-hour hour + AM/PM marker to 24-hour. No marker → already 24h."""
    if not ampm:
        return hour % 24
    marker = ampm.lower().replace(".", "")
    if marker == "pm" and hour != 12:
        return (hour + 12) % 24
    if marker == "am" and hour == 12:
        return 0
    return hour % 24


@dataclass
class _Slot:
    start: dtime
    end: dtime | None
    text: str


def _split_slots(plan_text: str) -> list[_Slot]:
    """Split free text into (start[-end], activity) slots by its embedded time markers.

    Slots are returned **sorted by start time**, not by where they appear in the text — the model
    may write times out of order or mix 12h/24h notation, and chronological lookup must not depend
    on text-appearance order. Each slot's text is still the substring that followed its own time
    marker in the original text (position-based extraction, independent of the later sort).
    """
    matches = list(_TIME_RANGE_RE.finditer(plan_text))
    slots: list[_Slot] = []
    for i, m in enumerate(matches):
        start = dtime(_to_24h(int(m.group("h1")), m.group("ap1")), int(m.group("m1")))
        end = None
        if m.group("h2"):
            end = dtime(_to_24h(int(m.group("h2")), m.group("ap2")), int(m.group("m2")))
        text_start = m.end()
        text_end = matches[i + 1].start() if i + 1 < len(matches) else len(plan_text)
        slots.append(_Slot(start, end, plan_text[text_start:text_end].strip(" .,;\n")))
    return sorted(slots, key=lambda s: s.start)


def current_activity(plan_text: str, now_local: datetime) -> str:
    """Derive "what she's doing now" from the free-text plan + the current local time.

    Finds the slot whose time window contains `now_local`'s time-of-day (or the most recent slot
    that has started, for open-ended entries). If the plan has no parseable time markers, the whole
    plan text is returned as a graceful fallback (NFR-006-03 — never "no day", degrade gracefully).
    """
    slots = _split_slots(plan_text)
    if not slots:
        return plan_text.strip()  # unparseable — still serve *something*, never empty

    now_t = now_local.time()
    # Before the day's first slot has started (e.g. 3am), she is still in the *last* slot from the
    # overnight wrap (yesterday's late activity carries past midnight), not the day's first slot.
    current = slots[-1]
    for slot in slots:
        if slot.end is not None:
            if slot.start <= now_t < slot.end:
                return slot.text
            if slot.start <= now_t:
                current = slot
        elif slot.start <= now_t:
            current = slot
    return current.text


# ── compression triggers (FR-006-07) ────────────────────────────────────────────────────────────


def should_compress(count: int, scope: str, cfg: LifeEngineConfig = DEFAULT_CONFIG) -> bool:
    """Is there enough lower-level material to compress into `scope` (FR-006-07)?"""
    ratio = {
        "week": cfg.daily_per_week,
        "month": cfg.weekly_per_month,
        "year": cfg.monthly_per_year,
        "epoch": cfg.years_per_epoch,
    }.get(scope)
    if ratio is None:
        raise ValueError(f"unknown compression target scope: {scope!r}")
    return count >= ratio


def lower_scope_of(scope: str) -> str:
    """The scope one level below (e.g. 'week' → 'day')."""
    idx = SCOPES.index(scope)
    if idx == 0:
        raise ValueError(f"{scope!r} has no lower scope")
    return SCOPES[idx - 1]


# ── fixed-anchor directive (FR-006-14) ──────────────────────────────────────────────────────────


def fixed_anchors_text(persona_name: str, big_five: str) -> str:
    """Render the persona's immutable identity anchors for a prompt (never rewritten — FR-006-14)."""
    return f"name: {persona_name}; core personality (Big Five): {big_five or 'not yet defined'}"
