"""F-002 conversation-turn tests (thin vertical slice).

Each test maps to a `TC-` id from developer files/tests/F-002-conversation-and-memory.md. Covers the
implemented slice: context assembly incl. recent raw history verbatim (FR-002-03/04), the LLM call
and reply (FR-002-05/07), persistence of both messages (FR-002-09), the empty-history first turn
(FR-002-17), post-processing (FR-002-06), the in-character rule in the persona prompt (FR-002-08),
and graceful in-character fallback when the runner is unavailable (FR-002-19). Memory/relationship/
styling are deferred (F-004/F-005/F-003) and not asserted here.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import func, select

from services.bot.chat_client import ChatClient, ChatRunnerUnavailable
from services.bot.domain import messages as msg_domain
from services.bot.domain.persona_prompt import build_system_prompt
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import conversation as conv
from services.bot.models import Message, MessageSender, Persona
from services.bot.orchestrator import _postprocess, handle_turn


# ── fakes ────────────────────────────────────────────────────────────────────────────────────


class FakeChatClient:
    """Records the messages it was called with and returns a canned reply."""

    def __init__(self, reply: str = "ну привет)) как ты сам?") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def is_ready(self) -> bool:
        return True

    async def complete(self, messages, **kw) -> str:
        self.calls.append(messages)
        return self.reply


class FailingChatClient:
    async def is_ready(self) -> bool:
        return False

    async def complete(self, messages, **kw) -> str:
        raise ChatRunnerUnavailable("runner down")


async def _ready_chat(db, *, language: str = "ru"):
    """Create a (user, persona, active session) trio and return them."""
    user, _ = await get_or_create_user(db, telegram_id=5001, locale=language)
    persona = Persona(name="Alina", profession="psychologist", age=28, language=language,
                      card_description="I'm Alina, I love the gym and deep talks.",
                      big_five="warm, playful, high openness")
    db.add(persona)
    await db.flush()
    session, _ = await start_or_switch_session(db, user.id, persona.id)
    return user, persona, session


def fake_message(tg_id: int, text: str, lang: str = "ru"):
    m = MagicMock(name="Message")
    m.from_user = SimpleNamespace(id=tg_id, language_code=lang)
    m.chat = SimpleNamespace(id=tg_id)
    m.text = text
    m.answer = AsyncMock()
    return m


# ── FR-002-05/07 — call the LLM, return an in-character reply ───────────────────────────────────


async def test_fr_002_07_01_returns_reply(db):
    """TC-FR-002-07-01 — the turn returns the model's reply text."""
    _, persona, session = await _ready_chat(db)
    client = FakeChatClient(reply="привет! только с тренировки, вся в тонусе 😄")
    reply = await handle_turn(db, session, persona, "привет, как ты?", client)
    assert reply == "привет! только с тренировки, вся в тонусе 😄"


# ── FR-002-03/04 — context assembly incl. recent raw history verbatim ──────────────────────────


async def test_fr_002_03_01_context_has_system_then_history(db):
    """TC-FR-002-03-01 — assembled context starts with the persona system prompt, then chat turns."""
    _, persona, session = await _ready_chat(db)
    client = FakeChatClient()
    await handle_turn(db, session, persona, "как дела?", client)
    sent = client.calls[0]
    assert sent[0]["role"] == "system"
    assert "Alina" in sent[0]["content"]
    assert sent[-1] == {"role": "user", "content": "как дела?"}


async def test_fr_002_04_01_recent_history_verbatim(db):
    """TC-FR-002-04-01 — prior messages are carried into the prompt verbatim, in order."""
    _, persona, session = await _ready_chat(db)
    # seed a prior exchange
    await msg_domain.append_message(db, session.id, MessageSender.user, "ты где живёшь?")
    await msg_domain.append_message(db, session.id, MessageSender.persona, "в москве, а ты?")
    client = FakeChatClient()
    await handle_turn(db, session, persona, "тоже мск", client)

    convo = [m for m in client.calls[0] if m["role"] != "system"]
    assert convo == [
        {"role": "user", "content": "ты где живёшь?"},
        {"role": "assistant", "content": "в москве, а ты?"},
        {"role": "user", "content": "тоже мск"},
    ]


async def test_fr_002_17_01_first_turn_empty_history(db):
    """TC-FR-002-17-01 — first message (no prior history) still yields a reply; history is just it."""
    _, persona, session = await _ready_chat(db)
    client = FakeChatClient(reply="хэй)")
    reply = await handle_turn(db, session, persona, "привет", client)
    assert reply == "хэй)"
    convo = [m for m in client.calls[0] if m["role"] != "system"]
    assert convo == [{"role": "user", "content": "привет"}]


# ── FR-002-09 — persist both messages with correct sender + order ──────────────────────────────


async def test_fr_002_09_01_persists_user_and_persona_messages(db):
    """TC-FR-002-09-01 — a user MESSAGE and a persona MESSAGE are stored for the turn, in order."""
    _, persona, session = await _ready_chat(db)
    client = FakeChatClient(reply="ага, слушаю")
    await handle_turn(db, session, persona, "есть минутка?", client)

    rows = (
        await db.execute(select(Message).where(Message.session_id == session.id).order_by(Message.id))
    ).scalars().all()
    assert [(m.sender, m.text) for m in rows] == [
        (MessageSender.user, "есть минутка?"),
        (MessageSender.persona, "ага, слушаю"),
    ]


# ── FR-002-19 — runner unavailable → in-character fallback, input preserved, never silent ──────


async def test_fr_002_19_01_fallback_on_unavailable(db):
    """TC-FR-002-19-01 — when the runner fails, a graceful in-character fallback is returned."""
    _, persona, session = await _ready_chat(db, language="ru")
    reply = await handle_turn(db, session, persona, "ты тут?", FailingChatClient())
    assert reply  # never empty/silent
    assert "AI" not in reply and "model" not in reply.lower()  # stays in character


async def test_fr_002_19_02_user_message_persisted_on_failure(db):
    """TC-FR-002-19-02 — the user's message is persisted even when generation fails (no input lost)."""
    _, persona, session = await _ready_chat(db)
    await handle_turn(db, session, persona, "важное сообщение", FailingChatClient())
    user_rows = (
        await db.execute(
            select(func.count()).select_from(Message).where(
                Message.session_id == session.id, Message.sender == MessageSender.user
            )
        )
    ).scalar_one()
    assert user_rows == 1


# ── FR-002-06 — post-processing ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<think>\nreasoning\n</think>\n\nпривет!", "привет!"),
        ("  hey there  ", "hey there"),
        ("no tags here", "no tags here"),
    ],
)
def test_fr_002_06_01_postprocess_strips_think_and_trims(raw, expected):
    """TC-FR-002-06-01 — post-processing strips any stray <think> block and trims whitespace."""
    assert _postprocess(raw) == expected


# ── FR-002-08 — the persona prompt forbids AI disclosure and sets the reply language ───────────


def test_fr_002_08_01_prompt_forbids_ai_disclosure():
    """TC-FR-002-08-01 — the system prompt bans admitting AI/bot/assistant and assistant closers."""
    p = Persona(name="Alina", profession="psychologist", age=28, language="ru",
                card_description="", big_five="")
    prompt = build_system_prompt(p)
    low = prompt.lower()
    assert "not a program" in low or "never say" in low
    assert "ai" in low  # explicitly names the thing she must not reveal
    assert "Russian" in prompt  # reply-language instruction (FR-002-21)


def test_fr_002_21_01_prompt_sets_english_for_en_persona():
    """TC-FR-002-21-01 — an English persona is instructed to reply in English."""
    p = Persona(name="Olivia", profession="artist", age=30, language="en",
                card_description="", big_five="")
    assert "English" in build_system_prompt(p)


# ── FR-002-04 — recent-history helpers (order + limit + role mapping) ──────────────────────────


async def test_fr_002_04_02_load_recent_orders_and_limits(db):
    """TC-FR-002-04-02 — load_recent returns the last N in chronological order."""
    _, _, session = await _ready_chat(db)
    for i in range(20):
        await msg_domain.append_message(db, session.id, MessageSender.user, f"m{i}")
    recent = await msg_domain.load_recent(db, session.id, limit=5)
    assert [m.text for m in recent] == ["m15", "m16", "m17", "m18", "m19"]


def test_fr_002_04_03_role_mapping():
    """TC-FR-002-04-03 — persona→assistant, user→user in the OpenAI mapping."""
    rows = [
        Message(sender=MessageSender.user, text="hi"),
        Message(sender=MessageSender.persona, text="hey"),
    ]
    assert msg_domain.to_openai_messages(rows) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hey"},
    ]


# ── ChatClient wire contract (mocked transport, no real server) ────────────────────────────────


def _mock_transport(handler):
    return httpx.MockTransport(handler)


async def test_chat_client_complete_ok():
    """TC-FR-002-05-01 — a 200 chat-completion yields the assistant text."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "  hello  "}}]})

    client = ChatClient(transport=_mock_transport(handler))
    assert await client.complete([{"role": "user", "content": "hi"}]) == "hello"


async def test_chat_client_raises_on_5xx():
    """TC-FR-002-19-03 — a 5xx from the runner raises ChatRunnerUnavailable (→ fallback upstream)."""
    client = ChatClient(transport=_mock_transport(lambda r: httpx.Response(503)))
    with pytest.raises(ChatRunnerUnavailable):
        await client.complete([{"role": "user", "content": "hi"}])


async def test_chat_client_raises_on_empty_completion():
    """TC-FR-002-19-04 — an empty completion is treated as unavailable, not sent as a blank reply."""
    client = ChatClient(
        transport=_mock_transport(
            lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]})
        )
    )
    with pytest.raises(ChatRunnerUnavailable):
        await client.complete([{"role": "user", "content": "hi"}])


async def test_chat_client_is_ready_true_false():
    """TC-NFR-002-12-01 — is_ready reflects the runner's /v1/models readiness."""
    ready = ChatClient(transport=_mock_transport(
        lambda r: httpx.Response(200, json={"data": [{"id": "qwen"}]})))
    down = ChatClient(transport=_mock_transport(lambda r: httpx.Response(503)))
    assert await ready.is_ready() is True
    assert await down.is_ready() is False


# ── handler-level (FR-002-01/24) ───────────────────────────────────────────────────────────────


async def test_fr_002_24_01_handler_sends_typing_then_reply(db, monkeypatch):
    """TC-FR-002-24-01 — the handler shows 'typing…' immediately, then answers with the reply."""
    monkeypatch.setattr(conv, "_sleep", AsyncMock())  # skip the real F-003 pacing pauses
    user, persona, session = await _ready_chat(db)
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    msg = fake_message(user.telegram_id, "привет", lang="ru")
    await conv.on_text(msg, db, bot, FakeChatClient(reply="хэй, рада тебя видеть)"))

    assert bot.send_chat_action.await_count >= 1  # typing indicator shown (ack + per-chunk)
    msg.answer.assert_awaited_once_with("хэй, рада тебя видеть)")  # short reply → single message


async def test_fr_002_01_02_no_active_session_nudges_to_choose(db):
    """TC-FR-002-01-02 — typing before choosing a lady nudges to Choose Lady, no crash."""
    await get_or_create_user(db, telegram_id=777, locale="en")
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    msg = fake_message(777, "hey", lang="en")
    await conv.on_text(msg, db, bot, FakeChatClient())
    bot.send_chat_action.assert_not_awaited()
    msg.answer.assert_awaited_once()
    assert "Choose Lady" in msg.answer.await_args.args[0]
