"""F-001 onboarding handlers — the canonical screen flow (architecture.md §1.1):

    /start -> S2 Choose Lady directly (intro msg + card) -> (Start Chat) -> S3 Chat.

There is no separate Welcome/Start screen (removed by explicit product decision, FR-001-02
deprecated): `/start` renders the Choose Lady screen for a brand-new user and a returning user
alike. Handlers are thin: parse the update, call the pure domain logic, render via `views`. They are
module-level functions (also registered on `router`) so tests can call them with mocked aiogram
objects.
"""
from __future__ import annotations

import logging
import os
import time

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
from services.bot.domain import presentation
from services.bot.domain.gallery import list_gallery_personas
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.i18n import t
from services.bot.models import Persona, User
from services.bot.views import CardContent

log = logging.getLogger(__name__)
router = Router(name="onboarding")

# Sentinel for send_persona_intro's `photo_ref`: distinguishes "caller said no photo" (None) from
# "caller didn't override — use her gallery photo" (_UNSET). Used by the F-013 greeting hook.
_UNSET: object = object()

_CHOOSE_LADY_LABELS = {t("btn_choose_lady", "en"), t("btn_choose_lady", "ru")}

# Transient per-chat id of the gallery **intro** message, so we can delete it when entering the chat
# (FR-001-21). In-memory: fine for the single-process dev bot; a multi-instance gateway would move
# this to shared state (Redis/FSM), consistent with the stateless-gateway principle (architecture §3.1).
_intro_msg_ids: dict[int, int] = {}

# Rapid-duplicate-tap guard for Start Chat openers (FR-001-17 / ISS-001): remembers when an opener
# (full or resume) was last sent per (chat, persona). Within the window a duplicate tap is deduped;
# outside it a resumed session always gets a resume opener — never silence. In-memory, same
# single-process dev note as `_intro_msg_ids` above.
_OPENER_GUARD_S = 8.0
_opener_sent_at: dict[tuple[int, int], float] = {}


def _mark_opener_sent(chat_id: int, persona_id: int) -> None:
    _opener_sent_at[(chat_id, persona_id)] = time.monotonic()


def _opener_recently_sent(chat_id: int, persona_id: int) -> bool:
    ts = _opener_sent_at.get((chat_id, persona_id))
    return ts is not None and (time.monotonic() - ts) < _OPENER_GUARD_S


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

    Send-before-delete (architecture.md §1.3): the *new* intro is sent first and only then is any
    stale, previously-tracked intro deleted — so a send failure never leaves the chat without any
    intro at all. The new message's id is tracked for the later Start Chat deletion (FR-001-21)."""
    personas = await list_gallery_personas(db, user.locale)
    if not personas:
        return False
    if with_intro:
        intro_text, reply_kb = views.gallery_intro_view(user.locale)
        sent = await message.answer(intro_text, reply_markup=reply_kb)  # send new intro FIRST
        stale_mid = _intro_msg_ids.get(message.chat.id)
        mid = getattr(sent, "message_id", None)
        if mid is not None:
            _intro_msg_ids[message.chat.id] = mid
        if stale_mid is not None and stale_mid != mid:
            await _safe_delete_message(bot, message.chat.id, stale_mid)  # THEN drop the old one
    await _send_card(message, views.gallery_card_view(personas[0], 0, len(personas), user.locale))
    return True


async def send_persona_intro(
    bot: Bot,
    chat_id: int,
    persona: Persona,
    reply_markup: ReplyKeyboardMarkup | None = None,
    *,
    opener: str | None = None,
    photo_ref: str | None = _UNSET,
) -> str:
    """S3 intro (FR-001-11/18/20): video-note circle, else photo+opener, else text opener.

    The opener text always carries the reply keyboard (FR-001-12) — a single opener message, no
    separate "ready to chat" follow-up. Media (a circle or photo) is her first "she's real" hit.

    F-013 hook: `opener`/`photo_ref` let the caller substitute the live, time/context-aware greeting
    (services/bot/domain/presentation.py) for the static default while reusing this single-send
    fallback ladder. Both default to the F-001 static content, so callers that pass neither (and the
    F-001 tests that call this directly) see the original behavior. A `photo_ref` of `None` means
    "no photo" (text-only greeting), distinct from the `_UNSET` default ("use her gallery photo")."""
    opener = opener if opener is not None else views.intro_opener(persona)
    ref = persona.gallery_photo_ref if photo_ref is _UNSET else photo_ref
    circle = _photo_file(persona.intro_videonote_ref)
    if circle is not None:
        try:
            await bot.send_video_note(chat_id, video_note=circle)
            await bot.send_message(chat_id, opener, reply_markup=reply_markup)
            return "video_note"
        except Exception:  # pragma: no cover - defensive; fall through to text opener
            log.warning("intro video note failed for persona %s; using opener only", persona.id)

    photo = _photo_file(ref)
    if photo is not None:
        await bot.send_photo(chat_id, photo, caption=opener, reply_markup=reply_markup)
        return "photo"

    await bot.send_message(chat_id, opener, reply_markup=reply_markup)
    return "fallback"


# ── /start -> S2 directly ───────────────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession, bot: Bot) -> None:
    """FR-001-01/03/15 — create the user once, then render Choose Lady (S2) directly — for a
    brand-new user and a returning user alike; there is no separate Welcome screen (FR-001-02,
    deprecated). `/start` never resume-locks a mid-chat user; the active session is left intact —
    picking that same persona again on S2 just continues the chat (no menu/resume)."""
    user, _created = await get_or_create_user(
        db, message.from_user.id, getattr(message.from_user, "language_code", None)
    )
    await _open_gallery(message, bot, db, user, with_intro=True)
    await _safe_delete_own(message)  # FR-001-23: drop the /start command AFTER responding


# ── Gallery navigation ───────────────────────────────────────────────────────────────────────────


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
    """FR-001-10/11/12/14/17/21 — create/reuse/switch session, send the S3 opener, THEN clean up S2.

    Send-before-delete (architecture.md §1.3): the opener is sent and must succeed before the S2
    card + intro are deleted. If sending raises, the S2 messages are left in place (not deleted)
    and the exception propagates (logged by aiogram) rather than silently leaving the chat blank;
    `cb.answer()` still fires via `finally` so the tap doesn't spin forever.

    **Start Chat is never mute** (FR-001-17 / ISS-001): a brand-new/switched session gets the full
    S3 opener; a **resumed** same-persona session gets a short in-character resume opener — the bot
    can't see the user deleting the chat client-side, so silence + S2 cleanup left an empty chat.
    Only *rapid duplicate taps* (within `_OPENER_GUARD_S`) are deduplicated instead.
    """
    user = await _user_from(db, cb.from_user)
    persona_id = int(cb.data.split(":", 1)[1])
    persona = await _persona(db, persona_id)
    if persona is None:
        await cb.answer()
        return
    chat_id = cb.message.chat.id
    _, is_new_intro = await start_or_switch_session(db, user.id, persona_id)
    try:
        if is_new_intro:
            # F-013 hook (the ONLY F-013 edit to this F-001 handler): compose the live,
            # time/context-aware greeting card (greeting text + a fitting SFW archive photo) and
            # send it as the ONE S3 opener message. Content only — this handler still owns the
            # single send + the S2 cleanup + navigation (FR-013-03/10). Falls back to a text-only
            # greeting when the archive is empty (FR-013-08).
            card = await presentation.compose_presentation(db, persona)
            await send_persona_intro(
                bot, chat_id, persona, reply_markup=keyboards.reply_kb(user.locale),
                opener=card.text, photo_ref=card.photo_ref,
            )
            _mark_opener_sent(chat_id, persona_id)
        elif not _opener_recently_sent(chat_id, persona_id):  # resume — never silent (ISS-001)
            await bot.send_message(
                chat_id, views.resume_opener(persona),
                reply_markup=keyboards.reply_kb(user.locale),
            )
            _mark_opener_sent(chat_id, persona_id)
        # else: rapid duplicate tap within the guard window — the opener just sent covers it.
        # Only reached if the send above succeeded (or was deduped) — now safe to tidy up S2.
        await _safe_delete_own(cb.message)          # the persona-card message
        await _delete_tracked_intro(bot, chat_id)    # the gallery intro message
    finally:
        await cb.answer()


# ── Reply keyboard + menu navigation ─────────────────────────────────────────────────────────────


@router.message(F.text.in_(_CHOOSE_LADY_LABELS))
async def on_choose_lady_text(message: Message, db: AsyncSession, bot: Bot) -> None:
    """FR-001-13 — '💋 Choose Lady' reopens the gallery (card; the reply keyboard already persists)."""
    user = await _user_from(db, message.from_user)
    await _open_gallery(message, bot, db, user, with_intro=False)
    await _safe_delete_own(message)  # FR-001-24: drop the button-tap text after handling


# No main menu, ever (architecture.md §1.3): there is no "≡ Menu" button, no menu screen, and no
# "Resume chat" action. `on_choose_lady_text` above is the only navigation entry point besides
# the S2/S3 flow itself (there is no S1 — see FR-001-02, deprecated); resuming a chat is just
# picking the same persona again on S2 (FR-001-10 reuses the active session).
