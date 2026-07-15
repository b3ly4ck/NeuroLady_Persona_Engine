"""F-006 Life Engine — the external-LLM steps (Life Engine, architecture.md §3.5/§4.6).

Each step builds its prompt from a **versioned asset** (FR-006-19), calls the LLM, and returns
plain text (plan/reflection/compression) or a parsed structure (goal updates). On any failure the
step returns `None` so the caller preserves the last good state (FR-006-20). We reuse the local
chat runner as the "external LLM" (same modular boundary as F-004/F-005).

Privacy by construction (FR-006-06 / NFR-006-05): none of these builders take any per-user data —
only the persona's own identity, biography, goals, and generic aggregate colour. There is no code
path here that reads `USER_FACT` or any per-user conversation, so a user's private facts cannot
leak into her shared life story.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from services.bot.chat_client import ChatClient, ChatRunnerUnavailable
from services.bot.domain.life_engine import DEFAULT_CONFIG, LifeEngineConfig, fixed_anchors_text
from services.bot.prompts import load_prompt

log = logging.getLogger(__name__)


async def _call(chat_client: ChatClient, prompt: str, max_tokens: int = 350) -> str | None:
    try:
        return await chat_client.complete(
            [{"role": "user", "content": prompt}], temperature=0.4, max_tokens=max_tokens)
    except ChatRunnerUnavailable as exc:
        log.warning("Life Engine LLM call failed (preserving last good state): %s", exc)
        return None


# ── plan_day ─────────────────────────────────────────────────────────────────────────────────


async def run_plan_day(
    chat_client: ChatClient, persona_name: str, big_five: str,
    recent_biography: str, goals: str, yesterday: str,
    cfg: LifeEngineConfig = DEFAULT_CONFIG,
) -> str | None:
    """Generate today's free-text plan (FR-006-01/02). Returns None on failure (FR-006-20)."""
    prompt = load_prompt(cfg.plan_prompt_version).format(
        persona_name=persona_name, persona_traits=big_five or "warm and genuine",
        fixed_anchors=fixed_anchors_text(persona_name, big_five),
        recent_biography=recent_biography or "(just starting out)",
        goals=goals or "(no specific goals yet)",
        yesterday=yesterday or "(no prior day recorded)",
    )
    return await _call(chat_client, prompt)


# ── reflect_day ──────────────────────────────────────────────────────────────────────────────


async def run_reflect_day(
    chat_client: ChatClient, persona_name: str, big_five: str,
    plan_text: str, generic_colour: str, recent_biography: str,
    cfg: LifeEngineConfig = DEFAULT_CONFIG,
) -> str | None:
    """Generate her first-person end-of-day reflection (FR-006-05/06). None on failure."""
    prompt = load_prompt(cfg.reflect_prompt_version).format(
        persona_name=persona_name, persona_traits=big_five or "warm and genuine",
        fixed_anchors=fixed_anchors_text(persona_name, big_five),
        plan_text=plan_text or "(a quiet day)",
        generic_colour=generic_colour or "(nothing notable)",
        recent_biography=recent_biography or "(just starting out)",
    )
    return await _call(chat_client, prompt)


# ── compress ─────────────────────────────────────────────────────────────────────────────────


async def run_compress(
    chat_client: ChatClient, persona_name: str, big_five: str,
    lower_scope: str, upper_scope: str, entries: list[str],
    cfg: LifeEngineConfig = DEFAULT_CONFIG,
) -> str | None:
    """Compress `entries` (lower-scope texts) into one upper-scope gist (FR-006-07/09). None on fail."""
    numbered = "\n".join(f"{i+1}. {e}" for i, e in enumerate(entries))
    prompt = load_prompt(cfg.compress_prompt_version).format(
        persona_name=persona_name, persona_traits=big_five or "warm and genuine",
        fixed_anchors=fixed_anchors_text(persona_name, big_five),
        lower_scope=lower_scope, upper_scope=upper_scope,
        count=len(entries), entries=numbered,
    )
    return await _call(chat_client, prompt, max_tokens=250)


# ── update_goals ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GoalUpdate:
    progress: dict[int, str] = field(default_factory=dict)   # goal_id -> note
    complete: list[int] = field(default_factory=list)
    drop: list[int] = field(default_factory=list)
    add: list[dict] = field(default_factory=list)  # [{"description","priority","horizon"}]


def _parse_goal_update(raw: str) -> GoalUpdate | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        d = json.loads(raw[start : end + 1])
        progress = {int(p["id"]): str(p.get("note", "")) for p in d.get("progress", []) if "id" in p}
        return GoalUpdate(
            progress=progress,
            complete=[int(x) for x in d.get("complete", [])],
            drop=[int(x) for x in d.get("drop", [])],
            add=[a for a in d.get("add", []) if isinstance(a, dict) and a.get("description")],
        )
    except (ValueError, TypeError, KeyError):
        return None


async def run_update_goals(
    chat_client: ChatClient, persona_name: str, big_five: str,
    goals_text: str, recent_reflections: str,
    cfg: LifeEngineConfig = DEFAULT_CONFIG,
) -> GoalUpdate | None:
    """Progress/add/complete/drop goals from recent reflections (FR-006-12). None on failure."""
    prompt = load_prompt(cfg.goals_prompt_version).format(
        persona_name=persona_name, persona_traits=big_five or "warm and genuine",
        goals=goals_text or "(no goals yet)",
        recent_reflections=recent_reflections or "(none yet)",
    )
    raw = await _call(chat_client, prompt, max_tokens=300)
    if raw is None:
        return None
    return _parse_goal_update(raw)


# ── update_future (F-007 FR-007-06) ────────────────────────────────────────────────────────────

_FUTURE_HORIZONS = ("week", "month", "year", "epoch", "lifetime")


def _parse_future(raw: str) -> dict[str, str] | None:
    """Parse the strict-JSON future-self map. Returns {horizon: content} for the known horizons, or
    None if nothing usable was returned (caller then keeps the last good projections)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        d = json.loads(raw[start : end + 1])
    except (ValueError, TypeError):
        return None
    out = {h: str(d[h]).strip() for h in _FUTURE_HORIZONS if isinstance(d.get(h), str) and d[h].strip()}
    return out or None


async def run_update_future(
    chat_client: ChatClient, persona_name: str, big_five: str,
    recent_biography: str, goals: str,
    cfg: LifeEngineConfig = DEFAULT_CONFIG,
) -> dict[str, str] | None:
    """Re-author her future-self at each horizon from her latest biography + goals (FR-007-06).
    Returns {horizon: content} or None on failure (last good state preserved, FR-007-08)."""
    prompt = load_prompt(cfg.future_prompt_version).format(
        persona_name=persona_name, persona_traits=big_five or "warm and genuine",
        fixed_anchors=fixed_anchors_text(persona_name, big_five),
        recent_biography=recent_biography or "(just starting out)",
        goals=goals or "(no specific goals yet)",
    )
    raw = await _call(chat_client, prompt, max_tokens=400)
    if raw is None:
        return None
    return _parse_future(raw)
