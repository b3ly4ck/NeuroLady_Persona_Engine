"""Message persistence + recent-history recall (architecture.md §5.1 MESSAGE, DFD-1).

The recent raw history is a hard requirement of F-002 (FR-002-04): the last N messages of the live
dialogue go into the LLM context verbatim, in order. This module owns writing turns and reading
that window back.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import Message, MessageSender

# How many of the most recent messages are carried verbatim into the context (FR-002-04).
RECENT_HISTORY_LIMIT = 12


async def append_message(
    db: AsyncSession, session_id: int, sender: MessageSender, text: str
) -> Message:
    msg = Message(session_id=session_id, sender=sender, text=text)
    db.add(msg)
    await db.flush()
    return msg


async def load_recent(
    db: AsyncSession, session_id: int, limit: int = RECENT_HISTORY_LIMIT
) -> list[Message]:
    """Return the last `limit` messages of a session in chronological (oldest→newest) order."""
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()  # back to chronological order for the prompt
    return rows


def to_openai_messages(history: list[Message]) -> list[dict[str, str]]:
    """Map stored MESSAGE rows to OpenAI chat roles (persona → assistant, user → user)."""
    out: list[dict[str, str]] = []
    for m in history:
        role = "assistant" if m.sender == MessageSender.persona else "user"
        out.append({"role": role, "content": m.text})
    return out
