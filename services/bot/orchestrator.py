"""Conversation Orchestrator — one user turn end-to-end (architecture.md §3.2, DFD-1, F-002).

Thin vertical slice (agreed scope): message intake → load session → assemble context (persona
system prompt + recent raw history) → call the Chat-LLM runner → post-process → in-character reply
→ persist both MESSAGE rows. Long-term memory (F-004), relationship state (F-005) and human-likeness
styling (F-003) are deferred; their integration points are marked with TODO hooks so they slot in
without reshaping this loop.

Requirements realized here: FR-002-03/04 (assemble context incl. recent raw history verbatim),
FR-002-05 (call the LLM), FR-002-06 (post-process), FR-002-07 (in-character reply), FR-002-09
(persist the exchange), FR-002-17 (empty-history first turn), FR-002-19 (timeout/fail → graceful
in-character fallback, logged, user message still persisted, never silent).
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.chat_client import ChatClient, ChatRunnerUnavailable
from services.bot.domain import messages as msg_domain
from services.bot.domain.persona_prompt import build_system_prompt
from services.bot.models import MessageSender, Persona, Session

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


async def handle_turn(
    db: AsyncSession,
    session: Session,
    persona: Persona,
    user_text: str,
    chat_client: ChatClient,
) -> str:
    """Process one turn and return the reply text to send. Persists the user message and the reply.

    The user message is persisted *before* the LLM call so no input is lost if generation fails
    (FR-002-19).
    """
    # 1. Persist the inbound user message first (FR-002-09; input-preserved on failure FR-002-19).
    await msg_domain.append_message(db, session.id, MessageSender.user, user_text)

    # 2. Assemble the context: persona system prompt + recent raw history (verbatim) + this message.
    #    (The recent window already includes the just-persisted user message.)  FR-002-03/04.
    history = await msg_domain.load_recent(db, session.id)
    llm_messages = [{"role": "system", "content": build_system_prompt(persona)}]
    llm_messages += msg_domain.to_openai_messages(history)
    # TODO(F-004): fuse retrieved user facts + persona biography layers here (memory query).
    # TODO(F-005): prepend the relationship summary that colors tone.

    # 3. Call the Chat-LLM; on any failure fall back in-character (FR-002-05/19).
    try:
        reply = _postprocess(await chat_client.complete(llm_messages))
    except ChatRunnerUnavailable as exc:
        log.warning("chat runner unavailable, using in-character fallback: %s", exc)
        reply = _fallback_text(persona)

    # 4. Persist the persona reply so the thread stays coherent (FR-002-09).
    await msg_domain.append_message(db, session.id, MessageSender.persona, reply)
    # TODO(F-002 memory): extract+categorize+embed salient user facts off the hot path (FR-002-10..12/23).
    # TODO(F-005): update relationship signals from this exchange (FR-002-15).
    # TODO(F-003): apply human-likeness styling + paced/chunked delivery on top of `reply`.
    return reply
