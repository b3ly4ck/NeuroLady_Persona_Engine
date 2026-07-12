"""F-001 handler-flow tests — call handlers directly with mocked aiogram objects + a real in-memory DB.

Maps to TC ids for FR-001-01/02/03/05/06/10/11/12/13/15/17/18/20 and UC-001-01/02/04/05/07/08.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import func, select

from services.bot.app import build_dispatcher
from services.bot.domain.gallery import list_gallery_personas
from services.bot.domain.sessions import get_active_session, start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import onboarding as ob
from services.bot.models import Session, SessionState, User


def fake_message(tg_id: int, lang: str = "en", text: str | None = None):
    m = MagicMock(name="Message")
    m.from_user = SimpleNamespace(id=tg_id, language_code=lang)
    m.chat = SimpleNamespace(id=tg_id)
    m.text = text
    m.answer = AsyncMock()
    m.edit_text = AsyncMock()
    return m


def fake_callback(tg_id: int, data: str, lang: str = "en"):
    cb = MagicMock(name="CallbackQuery")
    cb.from_user = SimpleNamespace(id=tg_id, language_code=lang)
    cb.data = data
    msg = MagicMock(name="cb.message")
    msg.chat = SimpleNamespace(id=tg_id)
    msg.answer = AsyncMock()
    msg.edit_text = AsyncMock()
    cb.message = msg
    cb.answer = AsyncMock()
    return cb


# ── /start (UC-001-01, FR-001-01/02, FR-001-15) ─────────────────────────────────────────────


async def test_uc_001_01_start_creates_user_and_shows_welcome(seeded_db):
    """TC-FR-001-01-03 / TC-FR-001-02-03 — /start creates the user and shows the Welcome screen."""
    bot = AsyncMock()
    msg = fake_message(1001, lang="en")
    await ob.cmd_start(msg, seeded_db, bot)

    count = (await seeded_db.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1
    msg.answer.assert_awaited_once()
    sent_text = msg.answer.await_args.args[0]
    assert "NeuroLady AI" in sent_text


async def test_fr_001_15_02_returning_user_resumes(seeded_db):
    """TC-FR-001-15-02 — a returning user with an active session resumes (reply keyboard), no re-onboard."""
    user, _ = await get_or_create_user(seeded_db, 1002, "en")
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    await start_or_switch_session(seeded_db, user.id, persona.id)
    await seeded_db.commit()

    bot = AsyncMock()
    msg = fake_message(1002, lang="en")
    await ob.cmd_start(msg, seeded_db, bot)

    kwargs = msg.answer.await_args.kwargs
    assert kwargs.get("reply_markup") is not None  # reply keyboard = resumed chat, not Welcome


# ── Start -> gallery (UC-001-02, FR-001-03) ─────────────────────────────────────────────────


async def test_uc_001_02_start_button_opens_gallery(seeded_db):
    """TC-FR-001-03-03 — tapping Start edits the message into the first persona card."""
    await get_or_create_user(seeded_db, 1003, "en")
    cb = fake_callback(1003, data="start")
    await ob.on_start(cb, seeded_db, AsyncMock())
    cb.message.edit_text.assert_awaited_once()
    cb.answer.assert_awaited()


# ── Carousel navigation (UC-001-03, FR-001-05/06) ───────────────────────────────────────────


async def test_fr_001_06_03_nav_to_index(seeded_db):
    """TC-FR-001-06-03 — navigating to 'card:2' renders the card at index 2 with a '3/N' counter."""
    await get_or_create_user(seeded_db, 1004, "en")
    cb = fake_callback(1004, data="card:2")
    await ob.on_card_nav(cb, seeded_db, AsyncMock())
    cb.message.edit_text.assert_awaited_once()
    kb = cb.message.edit_text.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][1].text.startswith("3/")


# ── Start Chat (UC-001-04, FR-001-10/11/12/18/20) ───────────────────────────────────────────


async def test_uc_001_04_start_chat_intro_and_ready(seeded_db):
    """TC-FR-001-10/12/18 — Start Chat creates a session and sends ONE intro carrying the reply
    keyboard (no separate 'ready to chat' message — see CLAUDE.md preference against stacked
    nudges)."""
    await get_or_create_user(seeded_db, 1005, "en")
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    bot = AsyncMock()
    cb = fake_callback(1005, data=f"startchat:{persona.id}")
    await ob.on_start_chat(cb, seeded_db, bot)

    active = await get_active_session(seeded_db, (await get_or_create_user(seeded_db, 1005, "en"))[0].id)
    assert active is not None and active.persona_id == persona.id
    bot.send_message.assert_awaited_once()      # fallback intro (seed persona has no video note)
    bot.send_video_note.assert_not_awaited()    # FR-001-18 graceful fallback
    assert bot.send_message.await_args.kwargs.get("reply_markup") is not None  # keyboard on the intro
    cb.message.answer.assert_not_awaited()      # no second/duplicate "ready" message


async def test_fr_001_17_01_double_tap_start_chat_single_intro(seeded_db):
    """TC-FR-001-17-01 — double-tapping Start Chat yields one session and one intro."""
    await get_or_create_user(seeded_db, 1006, "en")
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    bot = AsyncMock()
    cb = fake_callback(1006, data=f"startchat:{persona.id}")
    await ob.on_start_chat(cb, seeded_db, bot)
    await ob.on_start_chat(cb, seeded_db, bot)  # rapid second tap

    sessions = (await seeded_db.execute(select(func.count()).select_from(Session))).scalar_one()
    assert sessions == 1
    assert bot.send_message.await_count == 1  # intro sent exactly once


async def test_fr_001_20_01_intro_belongs_to_selected_persona(seeded_db):
    """TC-FR-001-20-01 — the fallback intro names the selected persona (correct linkage)."""
    await get_or_create_user(seeded_db, 1007, "en")
    personas = await list_gallery_personas(seeded_db, "en")
    target = personas[1]
    bot = AsyncMock()
    cb = fake_callback(1007, data=f"startchat:{target.id}")
    await ob.on_start_chat(cb, seeded_db, bot)
    intro_text = bot.send_message.await_args.args[1]
    assert target.name in intro_text


# ── Reply-keyboard "Choose Lady" (UC-001-06, FR-001-13) ─────────────────────────────────────


async def test_fr_001_13_01_choose_lady_reopens_gallery(seeded_db):
    """TC-FR-001-13-01 — the '💋 Choose Lady' reply button reopens the gallery."""
    from services.bot.i18n import t

    await get_or_create_user(seeded_db, 1008, "en")
    msg = fake_message(1008, lang="en", text=t("btn_choose_lady", "en"))
    await ob.on_choose_lady_text(msg, seeded_db, AsyncMock())
    msg.answer.assert_awaited_once()  # a fresh gallery card message


# ── send_persona_intro fallback (FR-001-18) ─────────────────────────────────────────────────


async def test_fr_001_18_01_intro_fallback_without_videonote(seeded_db):
    """TC-FR-001-18-01 — a persona with no intro video note falls back to a text intro."""
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    persona.intro_videonote_ref = None
    bot = AsyncMock()
    kind = await ob.send_persona_intro(bot, chat_id=42, persona=persona)
    assert kind == "fallback"
    bot.send_message.assert_awaited_once()
    bot.send_video_note.assert_not_awaited()


# ── wiring smoke test ────────────────────────────────────────────────────────────────────────


def test_build_dispatcher_wires_without_error(sessionmaker):
    """The dispatcher builds (middleware + router registered) without a token/network."""
    dp = build_dispatcher(sessionmaker)
    assert dp is not None
