"""F-001 onboarding handlers — the canonical screen flow (architecture.md §1.1):

    /start -> S1 Welcome -> (Start) -> S2 Choose Lady (intro msg + card) -> (Start Chat) -> S3 Chat.

Handlers are thin: parse the update, call the pure domain logic, render via `views`. They are
module-level functions (also registered on `router`) so tests can call them with mocked aiogram
objects.
"""
from __future__ import annotations

import logging
import os

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot import keyboards, views
from services.bot.domain.gallery import list_gallery_personas
from services.bot.domain.sessions import get_active_session, start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.i18n import t
from services.bot.models import Persona, User
from services.bot.views import CardContent

log = logging.getLogger(__name__)
router = Router(name="onboarding")

_CHOOSE_LADY_LABELS = {t("btn_choose_lady", "en"), t("btn_choose_lady", "ru")}
_MENU_LABELS = {t("btn_menu", "en"), t("btn_menu", "ru")}

# Transient per-chat id of the gallery **intro** message, so we can delete it when entering the chat
# (FR-001-21). In-memory: fine for the single-process dev bot; a multi-instance gateway would move
# this to shared state (Redis/FSM), consistent with the stateless-gateway principle (architecture §3.1).
_intro_msg_ids: dict[int, int] = {}


# ── helpers ────────────────────────────────────────────────────────────────────────────────────


async def _safe_delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:  # pragma: no cover - message may be gone / too old; harmless
        log.debug("delete_message(%s, %s) failed", chat_id, message_id, exc_info=True)


async def _safe_delete_own(message: Message) -> None:
    """Delete a message we received (the user's command/tap). Bots may delete incoming messages in
    private chats. Best-effort — never break the flow if it fails (FR-001-23/24)."""
    try:
        await message.delete()
    except Exception:  # pragma: no cover - defensive
        log.debug("could not delete user message", exc_info=True)


async def _delete_tracked_intro(bot: Bot, chat_id: int) -> None:
    mid = _intro_msg_ids.pop(chat_id, None)
    if mid is not None:
        await _safe_delete_message(bot, chat_id, mid)


async def _user_from(db: AsyncSession, tg_user) -> User:
    user, _ = await get_or_create_user(db, tg_user.id, getattr(tg_user, "language_code", None))
    return user


async def _persona(db: AsyncSession, persona_id: int) -> Persona | None:
    return await db.get(Persona, persona_id)


def _photo_file(ref: str | None) -> FSInputFile | None:
    """Resolve a media path to a sendable file, or None to render a text-only card/intro."""
    return FSInputFile(ref) if ref and os.path.exists(ref) else None


async def _send_card(message: Message, card: CardContent) -> None:
    """Send the S2 persona card as a photo message (if a real photo exists) or a text message."""
    photo = _photo_file(card.photo_ref)
    if photo is not None:
        await message.answer_photo(photo, caption=card.body, reply_markup=card.keyboard)
    else:
        await message.answer(card.body, reply_markup=card.keyboard)


async def _edit_card(message: Message, card: CardContent) -> None:
    """FR-001-05 — update the card message in place on ◀/▶ (no new message appended)."""
    photo = _photo_file(card.photo_ref)
    is_photo_msg = bool(getattr(message, "photo", None))
    try:
        if is_photo_msg and photo is not None:
            await message.edit_media(
                InputMediaPhoto(media=photo, caption=card.body), reply_markup=card.keyboard
            )
        elif not is_photo_msg and photo is None:
            await message.edit_text(card.body, reply_markup=card.keyboard)
        else:  # media type changed (text<->photo across the roster) — replace the message
            await message.delete()
            await _send_card(message, card)
    except Exception:  # pragma: no cover - defensive: fall back to a fresh card message
        log.warning("card edit failed; sending a fresh card", exc_info=True)
        await _send_card(message, card)


async def _open_gallery(
    message: Message, bot: Bot, db: AsyncSession, user: User, *, with_intro: bool
) -> bool:
    """Open S2: optionally the intro message (with reply keyboard), then the first persona card.

    When it sends the intro, it remembers that message's id (and clears any previous one) so the
    intro can be deleted on Start Chat (FR-001-21)."""
    personas = await list_gallery_personas(db, user.locale)
    if not personas:
        return False
    if with_intro:
        await _delete_tracked_intro(bot, message.chat.id)  # clear a stale intro if any
        intro_text, reply_kb = views.gallery_intro_view(user.locale)
        sent = await message.answer(intro_text, reply_markup=reply_kb)
        mid = getattr(sent, "message_id", None)
        if mid is not None:
            _intro_msg_ids[message.chat.id] = mid
    await _send_card(message, views.gallery_card_view(personas[0], 0, len(personas), user.locale))
    return True


async def send_persona_intro(
    bot: Bot,
    chat_id: int,
    persona: Persona,
    reply_markup: ReplyKeyboardMarkup | None = None,
) -> str:
    """S3 intro (FR-001-11/18/20): video-note circle, else photo+opener, else text opener.

    The opener text always carries the reply keyboard (FR-001-12) — a single opener message, no
    separate "ready to chat" follow-up. Media (a circle or photo) is her first "she's real" hit.
    """
    opener = views.intro_opener(persona)
    circle = _photo_file(persona.intro_videonote_ref)
    if circle is not None:
        try:
            await bot.send_video_note(chat_id, video_note=circle)
            await bot.send_message(chat_id, opener, reply_markup=reply_markup)
            return "video_note"
        except Exception:  # pragma: no cover - defensive; fall through to text opener
            log.warning("intro video note failed for persona %s; using opener only", persona.id)

    photo = _photo_file(persona.gallery_photo_ref)
    if photo is not None:
        await bot.send_photo(chat_id, photo, caption=opener, reply_markup=reply_markup)
        return "photo"

    await bot.send_message(chat_id, opener, reply_markup=reply_markup)
    return "fallback"


# ── /start (S1) ─────────────────────────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession, bot: Bot) -> None:
    """FR-001-01/02/15 — create the user once; new user sees Welcome (S1), a returning user goes
    straight to Choose Lady (S2). `/start` never resume-locks a mid-chat user; any active session is
    left intact for `Menu -> Resume chat`."""
    user, created = await get_or_create_user(
        db, message.from_user.id, getattr(message.from_user, "language_code", None)
    )
    if created:
        text, kb = views.welcome_view(user.locale)
        await message.answer(text, reply_markup=kb)
    else:
        await _open_gallery(message, bot, db, user, with_intro=True)
    await _safe_delete_own(message)  # FR-001-23: drop the /start command AFTER responding


# ── Start -> S2 gallery ──────────────────────────────────────────────────────────────────────────


@router.callback_query(F.data == "start")
async def on_start(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    """FR-001-03 — open S2: intro message (with reply keyboard) + the first persona card."""
    user = await _user_from(db, cb.from_user)
    await _open_gallery(cb.message, bot, db, user, with_intro=True)
    await cb.answer()


@router.callback_query(F.data.startswith("card:"))
async def on_card_nav(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    """FR-001-05/06 — paginate to the card index in the callback data (card updated in place)."""
    user = await _user_from(db, cb.from_user)
    try:
        index = int(cb.data.split(":", 1)[1])
    except (ValueError, IndexError):
        index = 0
    personas = await list_gallery_personas(db, user.locale)
    if personas:
        total = len(personas)
        index = max(0, min(index, total - 1))
        await _edit_card(cb.message, views.gallery_card_view(personas[index], index, total, user.locale))
    await cb.answer()


@router.callback_query(F.data == "noop")
async def on_noop(cb: CallbackQuery) -> None:
    await cb.answer()  # the counter button


# ── Start Chat -> S3 ───────────────────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("startchat:"))
async def on_start_chat(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    """FR-001-10/11/12/14/17 — create/reuse/switch session, send one intro (once) with the keyboard."""
    user = await _user_from(db, cb.from_user)
    persona_id = int(cb.data.split(":", 1)[1])
    persona = await _persona(db, persona_id)
    if persona is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    _, is_new_intro = await start_or_switch_session(db, user.id, persona_id)
    # FR-001-21: remove BOTH S2 messages (card + intro) as we enter S3, so no gallery chrome lingers.
    await _safe_delete_own(cb.message)          # the persona-card message
    await _delete_tracked_intro(bot, chat_id)   # the gallery intro message
    if is_new_intro:  # FR-001-17: a reused (double-tapped) session does not re-send the intro
        await send_persona_intro(
            bot, chat_id, persona, reply_markup=keyboards.reply_kb(user.locale)
        )
    await cb.answer()


# ── Reply keyboard + menu navigation ─────────────────────────────────────────────────────────────


@router.message(F.text.in_(_CHOOSE_LADY_LABELS))
async def on_choose_lady_text(message: Message, db: AsyncSession, bot: Bot) -> None:
    """FR-001-13 — '💋 Choose Lady' reopens the gallery (card; the reply keyboard already persists)."""
    user = await _user_from(db, message.from_user)
    await _open_gallery(message, bot, db, user, with_intro=False)
    await _safe_delete_own(message)  # FR-001-24: drop the button-tap text after handling


@router.callback_query(F.data == "choose_lady")
async def on_choose_lady_cb(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    user = await _user_from(db, cb.from_user)
    await _open_gallery(cb.message, bot, db, user, with_intro=False)
    await cb.answer()


@router.message(F.text.in_(_MENU_LABELS))
async def on_menu_text(message: Message, db: AsyncSession, bot: Bot) -> None:
    """FR-001-16 — open the main menu."""
    user = await _user_from(db, message.from_user)
    text, kb = views.menu_view(user.locale)
    await message.answer(text, reply_markup=kb)
    await _safe_delete_own(message)  # FR-001-24: drop the button-tap text after handling


@router.callback_query(F.data == "resume")
async def on_resume(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    """FR-001-16 — 'Resume chat' returns to the active persona (or the gallery if none)."""
    user = await _user_from(db, cb.from_user)
    active = await get_active_session(db, user.id)
    if active is not None:
        persona = await _persona(db, active.persona_id)
        if persona is not None:
            await cb.message.answer(
                t("resumed", user.locale, name=persona.name),
                reply_markup=keyboards.reply_kb(user.locale),
            )
            await cb.answer()
            return
    await _open_gallery(cb.message, bot, db, user, with_intro=False)
    await cb.answer()
