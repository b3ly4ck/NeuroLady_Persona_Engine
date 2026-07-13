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

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.chat_client import ChatClient
from services.bot.domain.humanize import chunk_reply, pacing_delay, parse_settings
from services.bot.domain.sessions import get_active_session
from services.bot.domain.users import get_or_create_user
from services.bot.models import Persona
from services.bot.orchestrator import handle_turn

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
    message: Message, db: AsyncSession, bot: Bot, chat_client: ChatClient
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

    # Immediate acknowledgement — the chat never looks frozen while we generate (FR-002-24).
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    reply = await handle_turn(db, session, persona, message.text, chat_client)

    # F-003 human-likeness delivery: split a long reply into a few short messages and pace each
    # with a "typing…" indicator + a deliberate, capped pause, so it reads like a real person
    # texting rather than one instant block. Chunking preserves meaning (FR-003-38).
    settings = parse_settings(persona)
    for chunk in chunk_reply(reply, settings):
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        await _sleep(pacing_delay(chunk, settings))
        await message.answer(chunk)
