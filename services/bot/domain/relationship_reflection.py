"""F-005 relationship reflection — the external-LLM judgment step (Life Engine, architecture.md §4.6).

Assembles the reflection prompt (persona + current state + recent conversation + hard signals) from
a **versioned asset** (FR-005-11), calls the LLM, and parses the returned per-dimension deltas +
reasons + rewritten summary + breach/pushing flags (FR-005-06/08). On any failure it returns
`None` so the caller preserves the last good state (FR-005-27 / NFR-005-04). We reuse the local chat
runner as the "external LLM" (same modular boundary as fact extraction).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from services.bot.chat_client import ChatClient, ChatRunnerUnavailable
from services.bot.domain.relationship import RelState
from services.bot.prompts import load_prompt

log = logging.getLogger(__name__)

PROMPT_ASSET = "relationship_reflection_v1"  # versioned prompt id (FR-005-11)


@dataclass
class HardSignals:
    days_since: float
    msg_count: int
    warmth: str  # "warm" | "neutral" | "cold" | "unknown"


@dataclass
class ReflectionResult:
    dc: int
    dt: int
    da: int
    reasons: dict[str, str]
    summary: str
    breach: bool = False
    pushing_fast: bool = False


_POSITIVE = {"спасибо", "рад", "скучал", "нравишься", "люблю", "thanks", "miss", "love", "glad", "cute"}
_NEGATIVE = {"тупая", "заткнись", "shut", "stupid", "hate", "ненавижу", "бесишь"}


def compute_warmth(conversation: str) -> str:
    """Coarse warmth cue from the recent conversation text (FR-005-06 hard signal)."""
    toks = set(conversation.lower().split())
    pos, neg = len(toks & _POSITIVE), len(toks & _NEGATIVE)
    if pos == neg == 0:
        return "unknown"
    return "warm" if pos > neg else ("cold" if neg > pos else "neutral")


def build_prompt(
    persona_name: str, persona_traits: str, state: RelState, summary: str,
    conversation: str, signals: HardSignals,
) -> str:
    return load_prompt(PROMPT_ASSET).format(
        persona_name=persona_name, persona_traits=persona_traits or "warm and genuine",
        stage=state.stage, closeness=state.closeness, trust=state.trust, attraction=state.attraction,
        summary=summary or "(you've only just started talking)",
        days_since=round(signals.days_since, 1), msg_count=signals.msg_count, warmth=signals.warmth,
        conversation=conversation or "(no messages yet)",
    )


def _parse(raw: str) -> ReflectionResult | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        d = json.loads(raw[start : end + 1])
        deltas = d.get("deltas", {})
        reasons = d.get("reasons", {}) or {}
        return ReflectionResult(
            dc=int(deltas.get("closeness", 0)),
            dt=int(deltas.get("trust", 0)),
            da=int(deltas.get("attraction", 0)),
            reasons={k: str(v) for k, v in reasons.items()},
            summary=str(d.get("summary", "")).strip(),
            breach=bool(d.get("breach", False)),
            pushing_fast=bool(d.get("pushing_fast", False)),
        )
    except (ValueError, TypeError):
        return None


async def run_reflection(
    chat_client: ChatClient, persona_name: str, persona_traits: str,
    state: RelState, summary: str, conversation: str, signals: HardSignals,
) -> ReflectionResult | None:
    """Call the LLM to judge the relationship change. Returns None on any failure (preserve state)."""
    prompt = build_prompt(persona_name, persona_traits, state, summary, conversation, signals)
    try:
        raw = await chat_client.complete(
            [{"role": "system", "content": prompt}], temperature=0.3, max_tokens=400)
    except ChatRunnerUnavailable as exc:
        log.warning("relationship reflection skipped (LLM unavailable): %s", exc)
        return None
    return _parse(raw)
