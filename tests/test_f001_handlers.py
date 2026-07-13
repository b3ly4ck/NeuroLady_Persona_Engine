"""F-001 handler-flow tests — call handlers directly with mocked aiogram objects + a real in-memory DB.

Maps to TC ids for FR-001-01/02/03/05/06/10/11/12/13/15/17/18/20 and UC-001-01/02/04/05/07/08.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select

from services.bot.app import build_dispatcher
from services.bot.domain.gallery import list_gallery_personas
from services.bot.domain.sessions import get_active_session, start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import onboarding as ob
from services.bot.models import Session, User


@pytest.fixture(autouse=True)
def _clear_intro_tracking():
    """The gallery-intro id registry is module-global; isolate it between tests."""
    ob._intro_msg_ids.clear()
    yield
    ob._intro_msg_ids.clear()


def fake_message(tg_id: int, lang: str = "en", text: str | None = None):
    m = MagicMock(name="Message")
    m.from_user = SimpleNamespace(id=tg_id, language_code=lang)
    m.chat = SimpleNamespace(id=tg_id)
    m.text = text
    m.photo = None
    m.answer = AsyncMock()
    m.answer_photo = AsyncMock()
    m.edit_text = AsyncMock()
    m.delete = AsyncMock()
    return m


def fake_callback(tg_id: int, data: str, lang: str = "en"):
    cb = MagicMock(name="CallbackQuery")
    cb.from_user = SimpleNamespace(id=tg_id, language_code=lang)
    cb.data = data
    cb.message = fake_message(tg_id, lang)
    cb.answer = AsyncMock()
    return cb


# ── /start (UC-001-01, FR-001-01/02, FR-001-15) ─────────────────────────────────────────────


async def test_uc_001_01_start_creates_user_and_shows_welcome(seeded_db):
    """TC-FR-001-01-03 / TC-FR-001-02-03 — /start creates the user and shows the Welcome screen."""
    msg = fake_message(1001, lang="en")
    await ob.cmd_start(msg, seeded_db, AsyncMock())

    count = (await seeded_db.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1
    msg.answer.assert_awaited_once()
    text, kwargs = msg.answer.await_args.args[0], msg.answer.await_args.kwargs
    assert "Step into a realm" in text  # welcome copy
    assert kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "start"
    msg.delete.assert_awaited_once()  # FR-001-23: /start deleted after responding


async def test_fr_001_15_02_returning_user_start_goes_to_gallery(seeded_db):
    """TC-FR-001-15-02 — a returning user's /start goes straight to Choose Lady even mid-chat (no
    resume-lock); the active session is preserved for the menu's Resume."""
    user, _ = await get_or_create_user(seeded_db, 1002, "en")  # user already exists (returning)
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    await start_or_switch_session(seeded_db, user.id, persona.id)
    await seeded_db.commit()

    msg = fake_message(1002, lang="en")
    await ob.cmd_start(msg, seeded_db, AsyncMock())

    assert msg.answer.await_count == 2  # gallery intro + card, not a resume message
    intro_kwargs = msg.answer.await_args_list[0].kwargs
    labels = [b.text for row in intro_kwargs["reply_markup"].keyboard for b in row]
    assert any("Choose Lady" in x for x in labels)
    active = await get_active_session(seeded_db, user.id)  # session preserved, not ended
    assert active is not None and active.persona_id == persona.id


# ── Start -> S2 gallery (UC-001-02, FR-001-03) ──────────────────────────────────────────────


async def test_uc_001_02_start_opens_gallery_intro_and_card(seeded_db):
    """TC-FR-001-03-01 — tapping Start sends the intro message (with reply kb) + the first card."""
    await get_or_create_user(seeded_db, 1003, "en")
    cb = fake_callback(1003, data="start")
    await ob.on_start(cb, seeded_db, AsyncMock())

    assert cb.message.answer.await_count == 2  # intro message + card message
    intro_kwargs = cb.message.answer.await_args_list[0].kwargs
    labels = [b.text for row in intro_kwargs["reply_markup"].keyboard for b in row]
    assert any("Choose Lady" in x for x in labels)  # reply keyboard on the intro
    cb.answer.assert_awaited()


# ── Carousel navigation (UC-001-03, FR-001-05/06) ───────────────────────────────────────────


async def test_fr_001_06_03_nav_updates_card_in_place(seeded_db):
    """TC-FR-001-06-03 — 'card:2' edits the card message in place with a '3/N' counter."""
    await get_or_create_user(seeded_db, 1004, "en")
    cb = fake_callback(1004, data="card:2")
    await ob.on_card_nav(cb, seeded_db, AsyncMock())
    cb.message.edit_text.assert_awaited_once()  # text card edited in place, no new message
    kb = cb.message.edit_text.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][1].text.startswith("3/")


# ── Start Chat -> S3 (UC-001-04, FR-001-10/11/12/18/20) ─────────────────────────────────────


async def test_uc_001_04_start_chat_single_opener_with_keyboard(seeded_db):
    """TC-FR-001-10/11/12/18 — Start Chat creates a session and sends ONE opener carrying the reply
    keyboard (no separate 'ready' message; seed persona has no media -> text opener)."""
    await get_or_create_user(seeded_db, 1005, "en")
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    bot = AsyncMock()
    cb = fake_callback(1005, data=f"startchat:{persona.id}")
    await ob.on_start_chat(cb, seeded_db, bot)

    active = await get_active_session(seeded_db, (await get_or_create_user(seeded_db, 1005, "en"))[0].id)
    assert active is not None and active.persona_id == persona.id
    bot.send_message.assert_awaited_once()          # the opener (text; no media on seed)
    bot.send_video_note.assert_not_awaited()        # FR-001-18 graceful fallback
    assert bot.send_message.await_args.kwargs.get("reply_markup") is not None  # keyboard on opener
    cb.message.answer.assert_not_awaited()          # no second/duplicate message


async def test_fr_001_21_03_send_before_delete_failed_send_keeps_old_screen(seeded_db):
    """TC-FR-001-21-03 — if the S3 send fails, the S2 card/intro are NOT deleted (no blank chat)."""
    await get_or_create_user(seeded_db, 1101, "en")
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("network hiccup")
    cb = fake_callback(1101, data=f"startchat:{persona.id}")
    ob._intro_msg_ids[cb.message.chat.id] = 555

    with pytest.raises(RuntimeError):
        await ob.on_start_chat(cb, seeded_db, bot)

    cb.message.delete.assert_not_awaited()        # card NOT deleted
    bot.delete_message.assert_not_awaited()        # intro NOT deleted
    cb.answer.assert_awaited_once()                # callback still acknowledged (finally)


async def test_fr_001_21_01_start_chat_deletes_card_message(seeded_db):
    """TC-FR-001-21-01 — tapping Start Chat deletes the stale gallery-card message."""
    await get_or_create_user(seeded_db, 1009, "en")
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    cb = fake_callback(1009, data=f"startchat:{persona.id}")
    await ob.on_start_chat(cb, seeded_db, AsyncMock())
    cb.message.delete.assert_awaited_once()


async def test_fr_001_21_02_start_chat_deletes_intro_message(seeded_db):
    """TC-FR-001-21-02 — Start Chat deletes the tracked gallery intro message (not just the card)."""
    await get_or_create_user(seeded_db, 1102, "en")
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    bot = AsyncMock()
    cb = fake_callback(1102, data=f"startchat:{persona.id}")
    ob._intro_msg_ids[cb.message.chat.id] = 999  # simulate the intro message tracked on open
    await ob.on_start_chat(cb, seeded_db, bot)
    cb.message.delete.assert_awaited_once()  # the card
    bot.delete_message.assert_awaited_once_with(cb.message.chat.id, 999)  # the intro


async def test_fr_001_03_02_intro_id_tracked_on_open(seeded_db):
    """The gallery intro message id is remembered on open so it can be deleted on Start Chat."""
    await get_or_create_user(seeded_db, 1104, "en")
    cb = fake_callback(1104, data="start")
    cb.message.answer.return_value = SimpleNamespace(message_id=4242)
    await ob.on_start(cb, seeded_db, AsyncMock())
    assert ob._intro_msg_ids.get(cb.message.chat.id) == 4242


def test_fr_001_16_deprecated_no_menu_handlers_exist():
    """TC-FR-001-16 (deprecated) — no main menu: there is no menu/resume handler in the module."""
    assert not hasattr(ob, "on_menu_text")
    assert not hasattr(ob, "on_resume")
    assert not hasattr(ob, "on_choose_lady_cb")
    assert not hasattr(ob, "_MENU_LABELS")


async def test_fr_001_22_01_photo_on_card_and_opener(seeded_db, tmp_path):
    """TC-FR-001-22-01 — when a real photo file exists, the card and the opener are sent as photos."""
    img = tmp_path / "card.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd9")  # minimal dummy jpeg bytes
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    persona.gallery_photo_ref = str(img)

    # S2 card as a photo message
    msg = fake_message(1010, "en")
    card = ob.views.gallery_card_view(persona, 0, 1, "en")
    await ob._send_card(msg, card)
    msg.answer_photo.assert_awaited_once()
    msg.answer.assert_not_awaited()

    # S3 opener as a photo message
    bot = AsyncMock()
    kind = await ob.send_persona_intro(bot, 1010, persona)
    assert kind == "photo"
    bot.send_photo.assert_awaited_once()
    bot.send_message.assert_not_awaited()


async def test_fr_001_17_01_double_tap_start_chat_single_intro(seeded_db):
    """TC-FR-001-17-01 — double-tapping Start Chat yields one session and one opener."""
    await get_or_create_user(seeded_db, 1006, "en")
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    bot = AsyncMock()
    cb = fake_callback(1006, data=f"startchat:{persona.id}")
    await ob.on_start_chat(cb, seeded_db, bot)
    await ob.on_start_chat(cb, seeded_db, bot)  # rapid second tap

    sessions = (await seeded_db.execute(select(func.count()).select_from(Session))).scalar_one()
    assert sessions == 1
    assert bot.send_message.await_count == 1  # opener sent exactly once


async def test_fr_001_20_01_opener_belongs_to_selected_persona(seeded_db):
    """TC-FR-001-20-01 — the opener names the selected persona (correct linkage)."""
    await get_or_create_user(seeded_db, 1007, "en")
    target = (await list_gallery_personas(seeded_db, "en"))[1]
    bot = AsyncMock()
    cb = fake_callback(1007, data=f"startchat:{target.id}")
    await ob.on_start_chat(cb, seeded_db, bot)
    assert target.name in bot.send_message.await_args.args[1]


# ── Reply-keyboard "Choose Lady" (UC-001-06, FR-001-13) ─────────────────────────────────────


async def test_fr_001_13_01_choose_lady_reopens_gallery(seeded_db):
    """TC-FR-001-13-01 — the '💋 Choose Lady' reply button reopens the gallery (card message)."""
    from services.bot.i18n import t

    await get_or_create_user(seeded_db, 1008, "en")
    msg = fake_message(1008, lang="en", text=t("btn_choose_lady", "en"))
    await ob.on_choose_lady_text(msg, seeded_db, AsyncMock())
    msg.answer.assert_awaited_once()  # a fresh card message (reply keyboard already persists)
    msg.delete.assert_awaited_once()  # FR-001-24: the button-tap text is deleted after handling


# ── send_persona_intro fallback (FR-001-18) ─────────────────────────────────────────────────


async def test_fr_001_18_01_intro_fallback_without_media(seeded_db):
    """TC-FR-001-18-01 — a persona with no video note and no photo falls back to a text opener."""
    persona = (await list_gallery_personas(seeded_db, "en"))[0]
    persona.intro_videonote_ref = None
    persona.gallery_photo_ref = None
    bot = AsyncMock()
    kind = await ob.send_persona_intro(bot, chat_id=42, persona=persona)
    assert kind == "fallback"
    bot.send_message.assert_awaited_once()
    bot.send_video_note.assert_not_awaited()
    bot.send_photo.assert_not_awaited()


# ── wiring smoke test ────────────────────────────────────────────────────────────────────────


def test_build_dispatcher_wires_without_error(sessionmaker):
    """The dispatcher builds (middleware + router registered) without a token/network."""
    assert build_dispatcher(sessionmaker) is not None
