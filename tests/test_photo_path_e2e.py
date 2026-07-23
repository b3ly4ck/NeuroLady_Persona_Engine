"""The photo request path must actually RUN — not just look right in the source.

Why this file exists: the ISS-004 regression test asserted on the *source text* of the handler
(that `media_pacing_delay` appears before `serve_photo_request`). That passes even when the branch
raises on the first line — and it did: `parse_settings(persona, user)` was called with two
arguments against a one-argument signature, so every photo request died with a TypeError and the
user got **silence**, while all 762 tests stayed green.

These tests execute the real `on_text` photo branch end-to-end with fakes, so a signature/wiring
error in that path fails the suite.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import conversation as conv
from services.bot.models import MediaAsset, MediaKind, Persona


class FakeChatClient:
    def __init__(self, reply: str = "вот, держи 😊") -> None:
        self.reply = reply

    async def is_ready(self) -> bool:
        return True

    async def complete(self, messages, **kw) -> str:
        return self.reply


async def _setup(db, tmp_path, *, with_asset: bool = True):
    """A user in an active session with a persona who has one archive photo on disk."""
    user, _ = await get_or_create_user(db, 9500, "ru")
    persona = Persona(name="Alina", profession="psychologist", age=28, language="ru",
                      card_description="", big_five="")
    db.add(persona)
    await db.flush()
    await start_or_switch_session(db, user.id, persona.id)

    if with_asset:
        import json
        photos = tmp_path / "alina" / "photos"
        photos.mkdir(parents=True)
        from PIL import Image
        Image.new("RGB", (64, 64), (120, 120, 120)).save(photos / "MED-alina-00001.png")
        db.add(MediaAsset(
            id="MED-alina-00001", persona_id=persona.id, kind=MediaKind.photo,
            intimate=False, intimacy_level=0,
            storage_ref="media/alina/photos/MED-alina-00001.png",
            meta_json=json.dumps({"pose": "close selfie", "activity": "кофе",
                                  "location": "cafe", "time_of_day": "afternoon"}),
        ))
        await db.flush()

    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    msg = MagicMock()
    msg.from_user = SimpleNamespace(id=9500, language_code="ru")
    msg.chat = SimpleNamespace(id=9500)
    msg.text = "скинь фотку"          # the live phrasing that produced silence
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()
    return persona, bot, msg


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """The photo path deliberately sleeps 2-6 s (FR-003-42) — don't make the suite wait."""
    slept: list[float] = []

    async def fake_sleep(d: float) -> None:
        slept.append(d)

    monkeypatch.setattr(conv, "_sleep", fake_sleep)
    return slept


async def test_photo_request_path_executes_and_sends(db, tmp_path, monkeypatch, _no_real_sleep):
    """REGRESSION (silent failure): a photo request must produce a user-visible result."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    _, bot, msg = await _setup(db, tmp_path)

    await conv.on_text(msg, db, bot, FakeChatClient())

    sent_photo = msg.answer_photo.await_count
    sent_text = msg.answer.await_count
    assert sent_photo + sent_text > 0, "a photo request must never end in silence"


async def test_photo_request_is_paced_before_sending(db, tmp_path, monkeypatch, _no_real_sleep):
    """FR-003-42 / FR-012-13: the upload action + a real delay precede delivery."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    _, bot, msg = await _setup(db, tmp_path)

    await conv.on_text(msg, db, bot, FakeChatClient())

    assert _no_real_sleep, "the photo path must sleep before sending (ISS-004)"
    assert 2.0 <= _no_real_sleep[0] <= 6.0
    assert bot.send_chat_action.await_count >= 1


async def test_photo_request_without_archive_still_replies(db, tmp_path, monkeypatch,
                                                           _no_real_sleep):
    """An empty archive must degrade in-voice (FR-012-08), never silence."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    _, bot, msg = await _setup(db, tmp_path, with_asset=False)

    await conv.on_text(msg, db, bot, FakeChatClient())

    assert msg.answer.await_count + msg.answer_photo.await_count > 0


async def test_ordinary_message_still_takes_the_text_path(db, tmp_path, monkeypatch,
                                                          _no_real_sleep):
    """The photo branch must not swallow normal conversation."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    _, bot, msg = await _setup(db, tmp_path)
    msg.text = "как у тебя дела?"

    await conv.on_text(msg, db, bot, FakeChatClient(reply="отлично, только с пробежки"))

    assert msg.answer.await_count >= 1
    assert msg.answer_photo.await_count == 0
