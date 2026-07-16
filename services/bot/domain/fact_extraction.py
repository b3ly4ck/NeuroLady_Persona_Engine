"""LLM-based user-fact extraction + supersession (F-004 FR-004-06/07/11/14/15).

Given the user's latest message and his already-stored active facts, one LLM call returns the
memory operations to apply: new salient facts to add (each categorized + confidence-scored) and the
ids of existing facts the new information supersedes (he said X before, now not-X). This runs
**off the reply hot path** (after the reply is delivered), so it never delays what the user sees
(FR-004-42/43, NFR-004-11).

The vector/semantic half (embedding the facts into Qdrant) is deferred — this slice is
Postgres-only structured memory.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from services.bot.chat_client import BRIEF_REASONING_DIRECTIVE, ChatClient, ChatRunnerUnavailable

log = logging.getLogger(__name__)

# Core categories (extensible — an unmapped topic falls back to "other", FR-004-07).
CATEGORIES = ("family", "work", "preferences", "complaints", "health", "plans", "other")

# Versioned extraction prompt asset (architecture.md §4.8 — prompts are per-module assets).
_SYSTEM_PROMPT = (
    "You extract durable personal facts a man reveals about himself in chat, for a companion's "
    "long-term memory. You are given his latest message and the facts already stored about him.\n"
    "Return STRICT JSON only, no prose, of the form:\n"
    '{"add": [{"category": "<one of: family|work|preferences|complaints|health|plans|other>", '
    '"content": "<short third-person fact, e.g. \'his sister Katya is getting married in June\'>", '
    '"confidence": <0.0-1.0>}], "supersede": [<id of an existing fact the new info contradicts/'
    "updates>]}\n"
    "Rules:\n"
    "- Only extract SALIENT, durable facts (relationships, work, where he lives, preferences, "
    "health, plans). Ignore small talk, greetings, and questions.\n"
    "- If he says nothing fact-worthy, return {\"add\": [], \"supersede\": []}.\n"
    "- confidence: 1.0 if he states it plainly; lower (e.g. 0.4) if hedged/uncertain (\"maybe\", "
    "\"i think\").\n"
    "- If the message updates or contradicts an existing stored fact, put that fact's id in "
    "\"supersede\" AND add the new version in \"add\".\n"
    "- Do NOT re-add a fact that is already stored unchanged (avoid duplicates).\n"
    "- content is always concise third-person about him."
)


@dataclass
class NewFact:
    category: str
    content: str
    confidence: float = 1.0


@dataclass
class MemoryOps:
    add: list[NewFact] = field(default_factory=list)
    supersede: list[int] = field(default_factory=list)


def _existing_facts_block(existing: list[tuple[int, str, str]]) -> str:
    if not existing:
        return "(none stored yet)"
    return "\n".join(f"- id={fid} [{cat}] {content}" for fid, cat, content in existing)


def _parse(raw: str) -> MemoryOps:
    """Parse the model's JSON reply defensively (it may wrap JSON in stray text)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return MemoryOps()
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError:
        return MemoryOps()

    ops = MemoryOps()
    for item in data.get("add", []) or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        category = str(item.get("category", "other")).strip().lower()
        if category not in CATEGORIES:
            category = "other"
        try:
            confidence = float(item.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        confidence = max(0.0, min(1.0, confidence))
        ops.add.append(NewFact(category=category, content=content, confidence=confidence))

    for fid in data.get("supersede", []) or []:
        try:
            ops.supersede.append(int(fid))
        except (TypeError, ValueError):
            continue
    return ops


async def extract_memory_ops(
    chat_client: ChatClient,
    user_message: str,
    existing: list[tuple[int, str, str]],
) -> MemoryOps:
    """Return the add/supersede operations for the user's latest message. Empty on any failure —
    memory extraction must never break the turn (it already ran after the reply was sent)."""
    payload = (
        f"His latest message:\n{user_message}\n\n"
        f"Facts already stored about him:\n{_existing_facts_block(existing)}"
    )
    try:
        raw = await chat_client.complete(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ],
            temperature=0.0,
            max_tokens=3072,  # CoT + JSON must both fit (reasoning ON, FR-003-41)
        )
    except ChatRunnerUnavailable as exc:
        log.warning("fact extraction skipped (runner unavailable): %s", exc)
        return MemoryOps()
    return _parse(raw)
