"""F-001 onboarding handlers: /start -> Welcome -> Choose Lady -> Start Chat -> ready chat.

Handlers are thin: they parse the update, call the pure domain logic, and render via `views`.
They are defined as module-level functions (and registered on `router`) so they can also be
called directly in tests with mocked aiogram objects.
"""
from __future__ import annotations

import logging
import os

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot import views
from services.bot.domain.gallery import list_gallery_personas
from services.bot.domain.sessions import get_active_session, start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.i18n import t
from services.bot.models import Persona, User

log = logging.getLogger(__name__)
router = Router(name="onboarding")

# Reply-keyboard button labels across all locales, so we match them regardless of the user's locale.
_CHOOSE_LADY_LABELS = {t("btn_choose_lady", "en"), t("btn_choose_lady", "ru")}
_MENU_LABELS = {t("btn_menu", "en"), t("btn_menu", "ru")}


async def _user_from(db: AsyncSession, tg_user) -> User:
    user, _ = await get_or_create_user(db, tg_user.id, getattr(tg_user, "language_code", None))
    return user


async def _persona(db: AsyncSession, persona_id: int) -> Persona | None:
    return await db.get(Persona, persona_id)


async def send_persona_intro(bot: Bot, chat_id: int, persona: Persona) -> str:
    """Deliver the persona's intro. Returns 'video_note' or 'fallback'.

    FR-001-11 (video-note circle from `intro_videonote_ref`), FR-001-18 (graceful text fallback if
    there is no usable circle), FR-001-20 (media belongs to the selected persona — it is *her* row),
    NFR-001-06 (a send error degrades to the fallback rather than crashing).
    """
    ref = persona.intro_videonote_ref
    if ref and os.path.exists(ref):
        try:
            await bot.send_video_note(chat_id, video_note=FSInputFile(ref))
            return "video_note"
        except Exception:  # pragma: no cover - defensive; falls through to text fallback
            log.warning("intro video note failed for persona %s; using fallback", persona.id)
    await bot.send_message(chat_id, t("intro_fallback", persona.language, name=persona.name))
    return "fallback"


async def _show_gallery_card(message: Message, db: AsyncSession, user: User, index: int, *, edit: bool) -> bool:
    """Render the gallery card at `index` (clamped). Returns False if the gallery is empty."""
    personas = await list_gallery_personas(db, user.locale)
    if not personas:
        return False
    total = len(personas)
    index = max(0, min(index, total - 1))
    text, kb = views.gallery_card_view(personas[index], index, total, user.locale)
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)
    return True


# ── /start ───────────────────────────────────────────────────────────────────────────────────


@router.message(CommandStart())
async def cmd_start(message: Message, db: AsyncSession, bot: Bot) -> None:
    """FR-001-01/02/15 — create the user (once); resume if they have an active session, else Welcome."""
    user = await _user_from(db, message.from_user)
    active = await get_active_session(db, user.id)
    if active is not None:
        persona = await _persona(db, active.persona_id)
        if persona is not None:
            text, kb = views.chat_ready_view(persona, user.locale)
            await message.answer(text, reply_markup=kb)
            return
    text, kb = views.welcome_view(user.locale)
    await message.answer(text, reply_markup=kb)


# ── Welcome "Start" -> gallery ────────────────────────────────────────────────────────────────


@router.callback_query(F.data == "start")
async def on_start(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    """FR-001-03 — open the Choose Lady gallery at the first card."""
    user = await _user_from(db, cb.from_user)
    await _show_gallery_card(cb.message, db, user, 0, edit=True)
    await cb.answer()


@router.callback_query(F.data.startswith("card:"))
async def on_card_nav(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    """FR-001-05/06 — paginate to the card index carried in the callback data."""
    user = await _user_from(db, cb.from_user)
    try:
        index = int(cb.data.split(":", 1)[1])
    except (ValueError, IndexError):
        index = 0
    await _show_gallery_card(cb.message, db, user, index, edit=True)
    await cb.answer()


@router.callback_query(F.data == "noop")
async def on_noop(cb: CallbackQuery) -> None:
    await cb.answer()  # the counter button: acknowledge so the client stops spinning


# ── Start Chat ────────────────────────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("startchat:"))
async def on_start_chat(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    """FR-001-10/11/12/14/17 — create/reuse/switch session, send intro (once), show reply keyboard."""
    user = await _user_from(db, cb.from_user)
    persona_id = int(cb.data.split(":", 1)[1])
    persona = await _persona(db, persona_id)
    if persona is None:
        await cb.answer()
        return
    _, is_new_intro = await start_or_switch_session(db, user.id, persona_id)
    if is_new_intro:  # FR-001-17: a reused (double-tapped) session does not re-send the intro
        await send_persona_intro(bot, cb.message.chat.id, persona)
    text, kb = views.chat_ready_view(persona, user.locale)
    await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


# ── Reply keyboard + menu navigation ─────────────────────────────────────────────────────────


@router.message(F.text.in_(_CHOOSE_LADY_LABELS))
async def on_choose_lady_text(message: Message, db: AsyncSession, bot: Bot) -> None:
    """FR-001-13 — '💋 Choose Lady' reopens the gallery."""
    user = await _user_from(db, message.from_user)
    await _show_gallery_card(message, db, user, 0, edit=False)


@router.callback_query(F.data == "choose_lady")
async def on_choose_lady_cb(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    user = await _user_from(db, cb.from_user)
    await _show_gallery_card(cb.message, db, user, 0, edit=True)
    await cb.answer()


@router.message(F.text.in_(_MENU_LABELS))
async def on_menu_text(message: Message, db: AsyncSession, bot: Bot) -> None:
    """FR-001-16 — open the main menu."""
    user = await _user_from(db, message.from_user)
    text, kb = views.menu_view(user.locale)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "resume")
async def on_resume(cb: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    """FR-001-16 — 'Resume chat' returns to the active persona (or the gallery if none)."""
    user = await _user_from(db, cb.from_user)
    active = await get_active_session(db, user.id)
    if active is not None:
        persona = await _persona(db, active.persona_id)
        if persona is not None:
            text, kb = views.chat_ready_view(persona, user.locale)
            await cb.message.answer(text, reply_markup=kb)
            await cb.answer()
            return
    await _show_gallery_card(cb.message, db, user, 0, edit=True)
    await cb.answer()
