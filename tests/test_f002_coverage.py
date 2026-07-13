"""F-002 supplementary coverage — automatable TC cases not covered by test_f002_conversation.py
(empty/blank input, recent-history windowing + trim, in-character fallback in both languages,
context assembly with no facts). Performance/load/manual TCs are out of scope (not fast unit tests).

Maps to `TC-` ids from developer files/tests/F-002-conversation-and-memory.md.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import re

from services.bot.chat_client import ChatRunnerUnavailable
from services.bot.domain import messages as msg_domain
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import conversation as conv
from services.bot.models import MessageSender, Persona
from services.bot.orchestrator import _FALLBACK, handle_turn

# System/AI tells checked as whole words (substring checks false-trip on e.g. "again" → "ai").
_TELL_WORDS = {"ai", "bot", "error", "ошибка", "model", "assistant", "system"}


def _has_system_tell(text: str) -> bool:
    return bool(_TELL_WORDS & set(re.findall(r"[a-zа-яё]+", text.lower())))


class FakeChatClient:
    def __init__(self, reply="ок)"):
        self.reply = reply
        self.calls = []

    async def is_ready(self):
        return True

    async def complete(self, messages, **kw):
        self.calls.append(messages)
        return self.reply


class FailingChatClient:
    async def is_ready(self):
        return False

    async def complete(self, messages, **kw):
        raise ChatRunnerUnavailable("down")


async def _ready_chat(db, tg_id=7001, language="ru"):
    user, _ = await get_or_create_user(db, telegram_id=tg_id, locale=language)
    persona = Persona(name="Alina", profession="psychologist", age=28, language=language,
                      card_description="", big_five="")
    db.add(persona)
    await db.flush()
    session, _ = await start_or_switch_session(db, user.id, persona.id)
    return user, persona, session


def _fake_message(tg_id, text, lang="ru"):
    m = MagicMock()
    m.from_user = SimpleNamespace(id=tg_id, language_code=lang)
    m.chat = SimpleNamespace(id=tg_id)
    m.text = text
    m.answer = AsyncMock()
    return m


# ── FR-002-01 — empty / blank input handled ────────────────────────────────────────────────────


async def test_fr_002_01_03_empty_message_no_crash(db):
    """TC-FR-002-01-03 — an empty message is ignored gracefully (no turn, no crash)."""
    bot = MagicMock(); bot.send_chat_action = AsyncMock()
    msg = _fake_message(7101, "", lang="ru")
    await conv.on_text(msg, db, bot, FakeChatClient())
    msg.answer.assert_not_awaited()
    bot.send_chat_action.assert_not_awaited()


async def test_fr_002_01_03_none_text_no_crash(db):
    """TC-FR-002-01-03 — a non-text (None) message is ignored gracefully."""
    bot = MagicMock(); bot.send_chat_action = AsyncMock()
    msg = _fake_message(7102, None, lang="ru")
    await conv.on_text(msg, db, bot, FakeChatClient())
    msg.answer.assert_not_awaited()


# ── FR-002-04 / FR-002-18 — recent-history window + trim ───────────────────────────────────────


async def test_fr_002_04_03_history_window_is_bounded(db):
    """TC-FR-002-04-03 — load_recent returns at most the configured window, newest kept."""
    _, _, session = await _ready_chat(db, tg_id=7201)
    for i in range(msg_domain.RECENT_HISTORY_LIMIT + 8):
        await msg_domain.append_message(db, session.id, MessageSender.user, f"m{i}")
    recent = await msg_domain.load_recent(db, session.id)
    assert len(recent) == msg_domain.RECENT_HISTORY_LIMIT
    assert recent[-1].text == f"m{msg_domain.RECENT_HISTORY_LIMIT + 7}"  # newest present


async def test_fr_002_18_02_trim_keeps_most_recent_in_order(db):
    """TC-FR-002-18-02 — after trimming, the kept messages are the most recent, in order."""
    _, _, session = await _ready_chat(db, tg_id=7202)
    for i in range(30):
        await msg_domain.append_message(db, session.id, MessageSender.user, f"x{i}")
    recent = await msg_domain.load_recent(db, session.id)
    texts = [m.text for m in recent]
    assert texts == sorted(texts, key=lambda t: int(t[1:]))  # chronological
    assert int(texts[0][1:]) < int(texts[-1][1:])  # oldest-in-window < newest


# ── FR-002-03 — context valid with no stored facts ─────────────────────────────────────────────


async def test_fr_002_03_03_context_valid_without_facts(db):
    """TC-FR-002-03-03 — with no stored facts the context is still a valid single system message."""
    _, persona, session = await _ready_chat(db, tg_id=7301)
    captured = {}

    class Capturing(FakeChatClient):
        async def complete(self, messages, **kw):
            captured["m"] = messages
            return "привет)"

    await handle_turn(db, session, persona, "хэй", Capturing())
    systems = [m for m in captured["m"] if m["role"] == "system"]
    assert len(systems) == 1 and "Alina" in systems[0]["content"]


# ── FR-002-19 / NFR-002-10 — in-character fallback, never system voice ──────────────────────────


async def test_fr_002_19_01_fallback_is_in_character_ru(db):
    """TC-FR-002-19-01 — RU runner failure yields an in-character RU fallback (no system/AI words)."""
    _, persona, session = await _ready_chat(db, tg_id=7401, language="ru")
    reply = await handle_turn(db, session, persona, "ты тут?", FailingChatClient())
    assert reply == _FALLBACK["ru"]
    assert not _has_system_tell(reply)


async def test_fr_002_19_01_fallback_is_in_character_en(db):
    """TC-FR-002-19-01 — EN runner failure yields an in-character EN fallback."""
    _, persona, session = await _ready_chat(db, tg_id=7402, language="en")
    reply = await handle_turn(db, session, persona, "you there?", FailingChatClient())
    assert reply == _FALLBACK["en"]
    assert not _has_system_tell(reply)


def test_nfr_002_10_01_fallback_strings_never_system_voice():
    """TC-NFR-002-10-01 — every fallback string reads in-character, not as a system/error message."""
    for text in _FALLBACK.values():
        assert not _has_system_tell(text)
