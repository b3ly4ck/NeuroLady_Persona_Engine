"""F-002 conversation handler — plain text in a ready chat becomes a persona reply.

Thin Telegram I/O layer over the Orchestrator (architecture.md §3.2, DFD-1). Registered on its own
router included *after* onboarding, so `/start`, the gallery callbacks, and the "💋 Choose Lady"
button keep priority; everything else the user types in an active session is a conversation turn.

A "typing…" chat action is sent immediately (FR-002-24 immediate acknowledgement; the F-003 typing
indicator), then the Orchestrator produces the reply (with an in-character fallback if the runner is
unavailable, so the chat is never left silent — FR-002-19).
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.chat_client import ChatClient
from services.bot.domain.gate_adapter import F014GateAdapter
from services.bot.domain.humanize import (
    chunk_reply,
    media_pacing_delay,
    pacing_delays,
    parse_settings,
)
from services.bot.domain.media_delivery import looks_like_photo_request
from services.bot.domain.sessions import get_active_session
from services.bot.domain.users import get_or_create_user
from services.bot.domain.vector_store import MemoryIndex
from services.bot.handlers.media import serve_photo_request
from services.bot.models import Persona
from services.bot.orchestrator import handle_turn, update_relationship, update_user_memory

log = logging.getLogger(__name__)
router = Router(name="conversation")

# Indirection so tests can stub out the deliberate pacing sleeps (F-003 pacing is real time).
_sleep = asyncio.sleep

# Neutral, localized nudge when the user types before choosing a persona (brand voice, not persona
# voice — no active session means there is no persona to speak in character yet).
_PICK_FIRST = {
    "ru": "выбери девушку через «💋 Choose Lady», и начнём 💬",
    "en": "pick a lady with “💋 Choose Lady” and we’ll get started 💬",
}


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(
    message: Message,
    db: AsyncSession,
    bot: Bot,
    chat_client: ChatClient,
    memory_index: MemoryIndex | None = None,
) -> None:
    tg_user = message.from_user
    if tg_user is None or not message.text:
        return
    user, _ = await get_or_create_user(db, tg_user.id, getattr(tg_user, "language_code", None))

    session = await get_active_session(db, user.id)
    if session is None:
        await message.answer(_PICK_FIRST.get(user.locale, _PICK_FIRST["en"]))
        return

    persona = await db.get(Persona, session.persona_id)
    if persona is None:  # defensive: session points at a removed persona
        await message.answer(_PICK_FIRST.get(user.locale, _PICK_FIRST["en"]))
        return

    # F-012/F-014 integration: a photo request short-circuits into media delivery (lookup+send,
    # no generation — F-008 NFR-008-04); everything else stays a normal conversation turn.
    if looks_like_photo_request(message.text):
        # FR-003-42 / FR-012-13 (ISS-004): a photo must not land instantly — show the upload action
        # for a bounded, length-independent beat first, the way a person takes a moment to send one.
        settings = parse_settings(persona)
        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_PHOTO)
        await _sleep(media_pacing_delay(settings))
        await serve_photo_request(
            message, db,
            user_id=user.id, persona=persona, request_text=message.text, context={},
            chat_client=chat_client, gate=F014GateAdapter(db),
        )
        await db.commit()
        return

    # Immediate acknowledgement — the chat never looks frozen while we generate (FR-002-24).
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    gen_started = time.monotonic()
    reply = await handle_turn(db, session, persona, message.text, chat_client, memory_index)
    gen_elapsed = time.monotonic() - gen_started

    # F-003 human-likeness delivery: split a long reply into a few short messages and pace each
    # with a "typing…" indicator + a deliberate, capped pause, so it reads like a real person
    # texting rather than one instant block. Chunking preserves meaning (FR-003-38). Generation
    # time (incl. the model's private reasoning) counts TOWARD the first pause (FR-003-41/
    # NFR-003-02): the gap the user already waited is not slept again on top.
    settings = parse_settings(persona)
    chunks = chunk_reply(reply, settings)
    delays = pacing_delays(chunks, settings)  # NFR-003-01 per-chunk + total budget
    if delays:
        delays[0] = max(0.3, delays[0] - gen_elapsed)
    for chunk, delay in zip(chunks, delays):
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await _sleep(delay)
        await message.answer(chunk)

    # AFTER the reply is delivered (off the hot path, FR-004-42/FR-005-03/NFR-005-03): extract +
    # store the user's facts (F-004) and run the relationship reflection (F-005). Neither delays what
    # he saw. (Production would move both to a background queue.)
    await update_user_memory(db, user.id, message.text, chat_client, memory_index)
    await update_relationship(db, session, persona, chat_client)
