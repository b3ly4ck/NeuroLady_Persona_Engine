"""Conversation Orchestrator — one user turn end-to-end (architecture.md §3.2, DFD-1, F-002).

Thin vertical slice (agreed scope): message intake → load session → assemble context (persona
system prompt + recalled user facts + recent raw history) → call the Chat-LLM runner → post-process
→ in-character reply → persist both MESSAGE rows; then (off the hot path) extract + store the user's
facts. Long-term **structured** memory (F-004, Postgres-only) is wired in here; the semantic/Qdrant
half plus relationship state (F-005) are deferred, their integration points marked with TODO hooks.

Requirements realized here: FR-002-03/04 (assemble context incl. recent raw history verbatim),
FR-002-05 (call the LLM), FR-002-06 (post-process), FR-002-07 (in-character reply), FR-002-09
(persist the exchange), FR-002-17 (empty-history first turn), FR-002-19 (timeout/fail → graceful
in-character fallback, logged, user message still persisted, never silent).
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.chat_client import ChatClient, ChatRunnerUnavailable
from services.bot.domain import memory as memory_domain
from services.bot.domain import messages as msg_domain
from services.bot.domain.fact_extraction import extract_memory_ops
from services.bot.domain.persona_prompt import build_system_prompt
from services.bot.domain.vector_store import MemoryIndex
from services.bot.models import MessageSender, Persona, Session, UserFact

log = logging.getLogger(__name__)

# In-character fallback when the runner can't answer (FR-002-19 / NFR-002-10) — never system voice.
_FALLBACK = {
    "ru": "ой, я на секунду отвлеклась… напиши ещё разок?",
    "en": "ugh sorry, my head's all over the place rn — say that again?",
}


def _fallback_text(persona: Persona) -> str:
    return _FALLBACK.get(persona.language, _FALLBACK["en"])


def _postprocess(text: str) -> str:
    """Minimal post-processing (FR-002-06). Thinking is disabled at the runner, but strip any
    stray <think>…</think> defensively and trim whitespace."""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    return text.strip()


def _memory_block(facts: list[UserFact], language: str) -> str | None:
    """Render recalled user facts as a system-context block (F-004 fused into the prompt, §4.2)."""
    if not facts:
        return None
    lines = "\n".join(f"- {f.content}" for f in facts)
    if language == "ru":
        return (
            "Что ты помнишь о нём (упоминай естественно и только когда уместно, "
            "не вываливай списком):\n" + lines
        )
    return (
        "What you remember about him (bring up naturally and only when relevant, "
        "don't dump it as a list):\n" + lines
    )


async def handle_turn(
    db: AsyncSession,
    session: Session,
    persona: Persona,
    user_text: str,
    chat_client: ChatClient,
    memory_index: MemoryIndex | None = None,
) -> str:
    """Process one turn and return the reply text to send. Persists the user message and the reply.

    The user message is persisted *before* the LLM call so no input is lost if generation fails
    (FR-002-19).
    """
    # 1. Persist the inbound user message first (FR-002-09; input-preserved on failure FR-002-19).
    await msg_domain.append_message(db, session.id, MessageSender.user, user_text)

    # 2. Assemble the context: ONE system message (persona prompt + recalled memory) + recent raw
    #    history + this message. The Qwen chat template allows only a single leading system message,
    #    so memory/relationship context is concatenated into it, not added as extra system turns.
    #    (The recent window already includes the just-persisted user message.)  FR-002-03/04.
    history = await msg_domain.load_recent(db, session.id)
    system_content = build_system_prompt(persona)
    # F-004: fuse the user's relevant stored facts into the context so she "remembers" (FR-002-13/14,
    # FR-004-24/28). Semantic search when a vector index is available, else keyword recall.
    recalled = await memory_domain.recall_relevant(db, session.user_id, user_text, memory_index)
    mem_block = _memory_block(recalled, persona.language)
    if mem_block:
        system_content += "\n\n" + mem_block
    # TODO(F-005): append the relationship summary that colors tone.
    llm_messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    llm_messages += msg_domain.to_openai_messages(history)

    # 3. Call the Chat-LLM; on any failure fall back in-character (FR-002-05/19).
    try:
        reply = _postprocess(await chat_client.complete(llm_messages))
    except ChatRunnerUnavailable as exc:
        log.warning("chat runner unavailable, using in-character fallback: %s", exc)
        reply = _fallback_text(persona)

    # 4. Persist the persona reply so the thread stays coherent (FR-002-09).
    await msg_domain.append_message(db, session.id, MessageSender.persona, reply)
    # TODO(F-005): update relationship signals from this exchange (FR-002-15).
    # TODO(F-003): apply human-likeness styling + paced/chunked delivery on top of `reply`.
    return reply


async def update_user_memory(
    db: AsyncSession,
    user_id: int,
    user_text: str,
    chat_client: ChatClient,
    memory_index: MemoryIndex | None = None,
) -> list[UserFact]:
    """Extract salient facts from the user's message and store them (F-004 FR-004-06/07/11/15).

    Called by the handler **after the reply is delivered**, so this LLM extraction never delays the
    user-visible reply (FR-002-23 / FR-004-42/43). When a vector `index` is given, new facts are
    also embedded and superseded ones removed (FR-004-08/33). Returns the newly-stored facts. Never
    raises — a memory failure must not affect the already-sent reply.
    """
    try:
        existing = [(f.id, f.category, f.content) for f in await memory_domain.active_facts(db, user_id)]
        ops = await extract_memory_ops(chat_client, user_text, existing)
        if not ops.add and not ops.supersede:
            return []
        return await memory_domain.apply_memory_ops(db, user_id, ops, memory_index)
    except Exception:  # pragma: no cover - defensive: memory must never break the turn
        log.warning("user-memory update failed", exc_info=True)
        return []
