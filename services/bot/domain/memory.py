"""User-fact memory store + recall (F-004, Postgres-only slice).

Owns the relational side of the memory system: storing categorized `USER_FACT` rows with
supersession/dedup (FR-004-06/07/11/12/15), and recalling a user's active facts ranked by
relevance to the current message (FR-004-09/13/24/25/26). All reads/writes are scoped to the acting
user (FR-004-36 / NFR-004-03). The semantic (Qdrant) half is deferred: ranking here is a
keyword-overlap + recency + confidence heuristic rather than embedding similarity.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain.fact_extraction import MemoryOps
from services.bot.models import FactStatus, UserFact

# How many recalled facts are fused into the reply context (FR-004-26 — bounded, don't dominate).
RECALL_LIMIT = 6
_TOKEN_RE = re.compile(r"[^\wа-яё]+", re.IGNORECASE | re.UNICODE)
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "i", "you", "he", "she", "it", "to", "of", "and",
    "и", "в", "на", "я", "ты", "он", "она", "это", "что", "как", "мне", "тебя", "не", "с",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.split(text.lower()) if len(t) > 2 and t not in _STOPWORDS}


async def active_facts(db: AsyncSession, user_id: int) -> list[UserFact]:
    """All of a user's active (non-superseded) facts, newest first. Scoped to the user (FR-004-36)."""
    stmt = (
        select(UserFact)
        .where(UserFact.user_id == user_id, UserFact.status == FactStatus.active)
        .order_by(UserFact.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def apply_memory_ops(db: AsyncSession, user_id: int, ops: MemoryOps) -> list[UserFact]:
    """Apply extraction results: supersede contradicted facts, dedup, insert new ones.

    Returns the newly-inserted facts. Supersession and dedup are scoped to the acting user so one
    user's memory can never touch another's (FR-004-36).
    """
    existing = await active_facts(db, user_id)
    existing_ids = {f.id for f in existing}
    existing_norm = {(f.category, f.content.strip().lower()) for f in existing}

    # 1. Insert new facts (skipping exact duplicates of an existing active fact — FR-004-15).
    inserted: list[UserFact] = []
    for nf in ops.add:
        key = (nf.category, nf.content.strip().lower())
        if key in existing_norm:
            continue  # dedup: same fact already stored
        fact = UserFact(
            user_id=user_id, category=nf.category, content=nf.content.strip(),
            status=FactStatus.active, confidence=nf.confidence,
        )
        db.add(fact)
        inserted.append(fact)
        existing_norm.add(key)
    await db.flush()  # assign ids to inserted facts

    # 2. Supersede contradicted facts (only this user's active facts — FR-004-11/12).
    replacement_id = inserted[0].id if inserted else None
    for fid in ops.supersede:
        if fid not in existing_ids:
            continue
        fact = await db.get(UserFact, fid)
        if fact is not None and fact.user_id == user_id and fact.status == FactStatus.active:
            fact.status = FactStatus.superseded
            fact.superseded_by = replacement_id
            fact.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return inserted


def _score(fact: UserFact, query_tokens: set[str], newest_id: int) -> float:
    """Relevance score: keyword overlap (primary) + recency + confidence (FR-004-13/25)."""
    overlap = len(_tokens(fact.content) & query_tokens)
    recency = (fact.id / newest_id) if newest_id else 0.0  # 0..1, newer → higher
    return overlap * 10.0 + recency * 2.0 + fact.confidence


async def recall_facts(
    db: AsyncSession, user_id: int, message: str, limit: int = RECALL_LIMIT
) -> list[UserFact]:
    """Return up to `limit` of the user's active facts most relevant to `message`.

    Ranked by keyword overlap, then recency and confidence (FR-004-09/13/25). Bounded by `limit`
    so irrelevant facts can't dominate the context (FR-004-26).
    """
    facts = await active_facts(db, user_id)
    if not facts:
        return []
    query_tokens = _tokens(message)
    newest_id = max(f.id for f in facts)
    ranked = sorted(facts, key=lambda f: _score(f, query_tokens, newest_id), reverse=True)
    return ranked[:limit]
