"""ISS-012 — the greeting / resume opener must be LLM-composed, not a hardcoded template.

Live report: re-entering an active chat always greeted with the identical fixed line
("Снова ты 😏 А я скучала… на чём мы остановились?"). It must be written by the model, fresh each
open, grounded in where the conversation left off — with the static line kept only as the fallback
when the model is unavailable (the resume moment is never silent).

Every test **executes the real path** — `presentation.compose_opener` and the `on_start_chat`
handler — with a fake chat client, and asserts on the observable outcome (what text was produced /
what reached the fake bot). No source-text assertions.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.bot import views
from services.bot.domain import presentation
from services.bot.domain.presentation import compose_opener
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import onboarding
from services.bot.models import Persona

pytestmark = pytest.mark.asyncio


class FakeChat:
    """Records the messages it was asked to complete; returns a scripted reply."""

    def __init__(self, reply: str = "вот свежее приветствие ✨", ready: bool = True,
                 raises: bool = False) -> None:
        self.reply = reply
        self.ready = ready
        self.raises = raises
        self.calls: list = []

    async def is_ready(self) -> bool:
        return self.ready

    async def complete(self, messages, **kw) -> str:
        self.calls.append(messages)
        if self.raises:
            raise RuntimeError("model down")
        return self.reply


async def _persona(db, *, name="Alina", language="ru") -> Persona:
    p = Persona(name=name, profession="psychologist", age=28, language=language,
                card_description="warm, flirty", big_five="", timezone="Europe/Moscow")
    db.add(p)
    await db.flush()
    return p


# ── FR-013-13 — the opener is the model's output, not a template ─────────────────────────────────


async def test_fr_013_13_01_resume_opener_uses_the_model_text(db):
    """TC-FR-013-13-01 — the composed resume opener IS the model's reply, not `resume_opener`."""
    persona = await _persona(db)
    client = FakeChat("Ну наконец-то ты вернулся, я как раз про тебя думала 😊")

    text = await compose_opener(persona, kind="resume", chat_client=client,
                                fallback=views.resume_opener(persona))

    assert text == "Ну наконец-то ты вернулся, я как раз про тебя думала 😊"
    assert text != views.resume_opener(persona)
    assert client.calls, "the model was never called"


async def test_fr_013_13_02_selection_greeting_uses_the_model_over_the_template(db):
    """TC-FR-013-13-02 — with a chat client, the presentation card text is model-composed."""
    persona = await _persona(db)
    await start_or_switch_session(db, (await get_or_create_user(db, 5001, "ru"))[0].id, persona.id)
    client = FakeChat("Привет! Я как раз рисую у окна, заходи 🎨")

    card = await presentation.compose_presentation(db, persona, chat_client=client)

    assert card.text == "Привет! Я как раз рисую у окна, заходи 🎨"
    assert client.calls


async def test_fr_013_13_03_resume_prompt_carries_the_last_exchange(db):
    """TC-FR-013-13-03 — recent messages reach the model so it can pick the thread back up."""
    persona = await _persona(db)
    client = FakeChat()
    recent = [
        {"role": "user", "content": "я обожаю горы"},
        {"role": "assistant", "content": "я тоже! мечтаю про Алтай"},
    ]

    await compose_opener(persona, kind="resume", chat_client=client,
                         fallback="x", recent=recent)

    sent = client.calls[0]
    joined = " ".join(m["content"] for m in sent)
    assert "горы" in joined and "Алтай" in joined, "the last exchange never reached the model"


async def test_fr_013_13_04_two_opens_request_fresh_generations(db):
    """TC-FR-013-13-04 — each open calls the model afresh (freshness comes from generation)."""
    persona = await _persona(db)
    client = FakeChat()

    await compose_opener(persona, kind="resume", chat_client=client, fallback="x")
    await compose_opener(persona, kind="resume", chat_client=client, fallback="x")

    assert len(client.calls) == 2


async def test_fr_013_13_05_resume_handler_sends_the_composed_opener(db, monkeypatch):
    """TC-FR-013-13-05 — the real resume handler path sends the model's opener, one message."""
    user, _ = await get_or_create_user(db, 5005, "ru")
    persona = await _persona(db)
    # an already-active session → the second Start Chat is a RESUME
    await start_or_switch_session(db, user.id, persona.id)
    monkeypatch.setattr(onboarding, "_opener_recently_sent", lambda *a, **k: False)

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_video_note = AsyncMock()
    cb = MagicMock()
    cb.data = f"startchat:{persona.id}"
    cb.from_user = SimpleNamespace(id=5005, language_code="ru")
    cb.message = SimpleNamespace(chat=SimpleNamespace(id=5005), delete=AsyncMock())
    cb.answer = AsyncMock()
    client = FakeChat("О, ты вернулся! Я скучала по нашим разговорам 💫")

    await onboarding.on_start_chat(cb, db, bot, chat_client=client)

    sent = [c.args[1] for c in bot.send_message.await_args_list if len(c.args) > 1]
    sent += [c.kwargs.get("text") for c in bot.send_message.await_args_list if c.kwargs.get("text")]
    assert "О, ты вернулся! Я скучала по нашим разговорам 💫" in sent


# ── FR-013-14 — degrade, never silence, never a leak ─────────────────────────────────────────────


async def test_fr_013_14_01_model_error_falls_back_to_static(db):
    """TC-FR-013-14-01 — a raising model yields the static line, never an exception."""
    persona = await _persona(db)
    fallback = views.resume_opener(persona)

    text = await compose_opener(persona, kind="resume", chat_client=FakeChat(raises=True),
                                fallback=fallback)

    assert text == fallback


async def test_fr_013_14_02_empty_reply_falls_back(db):
    """TC-FR-013-14-02 — an empty/whitespace reply never becomes an empty greeting."""
    persona = await _persona(db)

    for reply in ("", "   ", "\n\n"):
        text = await compose_opener(persona, kind="resume", chat_client=FakeChat(reply),
                                    fallback="СТАТИКА")
        assert text == "СТАТИКА"


async def test_fr_013_14_02b_not_ready_falls_back(db):
    """TC-FR-013-14-02 (boundary) — a not-ready model uses the fallback without calling complete."""
    persona = await _persona(db)
    client = FakeChat(ready=False)

    text = await compose_opener(persona, kind="resume", chat_client=client, fallback="СТАТИКА")

    assert text == "СТАТИКА" and client.calls == []


async def test_fr_013_14_03_media_signal_is_stripped_from_the_opener(db):
    """TC-FR-013-14-03 — a stray F-020 signal in the reply never reaches the greeting."""
    persona = await _persona(db)
    client = FakeChat("Привет, рада тебя видеть! 😊 <<MEDIA:photo:sfw>>")

    text = await compose_opener(persona, kind="resume", chat_client=client, fallback="x")

    assert "<<MEDIA" not in text and ">>" not in text
    assert "Привет, рада тебя видеть" in text


async def test_fr_013_14_04_resume_handler_never_silent_on_model_failure(db, monkeypatch):
    """TC-FR-013-14-04 — the resume handler still greets (static line) when the model fails."""
    user, _ = await get_or_create_user(db, 5006, "ru")
    persona = await _persona(db)
    await start_or_switch_session(db, user.id, persona.id)
    monkeypatch.setattr(onboarding, "_opener_recently_sent", lambda *a, **k: False)

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.send_video_note = AsyncMock()
    cb = MagicMock()
    cb.data = f"startchat:{persona.id}"
    cb.from_user = SimpleNamespace(id=5006, language_code="ru")
    cb.message = SimpleNamespace(chat=SimpleNamespace(id=5006), delete=AsyncMock())
    cb.answer = AsyncMock()

    await onboarding.on_start_chat(cb, db, bot, chat_client=FakeChat(raises=True))

    assert bot.send_message.await_count >= 1, "the resume moment went silent"
    sent = " ".join(str(c.args) + str(c.kwargs) for c in bot.send_message.await_args_list)
    assert views.resume_opener(persona) in sent


# ── FR-013-15 — shape / language ─────────────────────────────────────────────────────────────────


async def test_fr_013_15_02_instruction_pins_the_persona_language(db):
    """TC-FR-013-15-02 — the compose instruction names the persona's language (RU vs EN)."""
    ru = await _persona(db, name="Alina", language="ru")
    en = await _persona(db, name="Mia", language="en")
    ru_client, en_client = FakeChat(), FakeChat()

    await compose_opener(ru, kind="resume", chat_client=ru_client, fallback="x")
    await compose_opener(en, kind="selection", chat_client=en_client, fallback="x")

    assert "Russian" in ru_client.calls[0][0]["content"]
    assert "English" in en_client.calls[0][0]["content"]


async def test_fr_013_15_01_no_chat_client_keeps_the_static_line(db):
    """TC-FR-013-15-01 (compat) — without a chat client the behaviour is the old static line."""
    persona = await _persona(db)

    text = await onboarding._resume_opener(db, persona, None)

    assert text == views.resume_opener(persona)
