"""ISS-007 — a slow turn locked SQLite, the next message died, the user got total silence.

Two independent defects had to line up:
  1. the post-turn work (F-004 extraction, F-005 reflection) held a write transaction across two
     ~20-30 s LLM calls, so the next message's INSERT hit `database is locked` (busy_timeout 30 s);
  2. nothing caught that exception — the middleware rolls back and re-raises, `on_text` has no
     except, no error handler was registered — so the turn produced ZERO outbound messages.

Covers FR-002-27 (no write transaction across an LLM call), FR-002-28 (every inbound message ends
in a visible reply), FR-002-29 (post-turn work can't break the turn), NFR-002-14 (concurrency).
Every test EXECUTES the real path — a source-grepping test is what let a silent TypeError ship.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from pathlib import Path

from services.bot.app import _on_error
from services.bot.db import init_models, make_sessionmaker
from services.bot.domain.sessions import get_active_session, start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import conversation as conv
from services.bot.models import Message, Persona
from services.bot.orchestrator import handle_turn, update_relationship, update_user_memory


class SlowClient:
    """Simulates the real runner: generation takes real (short) time while we probe the DB."""

    def __init__(self, delay: float = 0.25, reply: str = "ага <<MEDIA:none>>") -> None:
        self.delay = delay
        self.reply = reply

    async def is_ready(self) -> bool:
        return True

    async def complete(self, messages, **kw) -> str:
        await asyncio.sleep(self.delay)
        return self.reply


class BoomClient:
    async def is_ready(self) -> bool:
        return True

    async def complete(self, messages, **kw) -> str:
        raise RuntimeError("model exploded")


def _msg(uid: int = 9800, text: str = "привет"):
    m = MagicMock()
    m.from_user = SimpleNamespace(id=uid, language_code="ru")
    m.chat = SimpleNamespace(id=uid)
    m.text = text
    m.answer = AsyncMock()
    m.answer_photo = AsyncMock()
    return m


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def fake_sleep(_d: float) -> None:
        return None
    monkeypatch.setattr(conv, "_sleep", fake_sleep)


async def _persona_session(db, uid: int = 9800):
    user, _ = await get_or_create_user(db, uid, "ru")
    persona = Persona(name="Alina", language="ru", card_description="", big_five="")
    db.add(persona)
    await db.flush()
    await start_or_switch_session(db, user.id, persona.id)
    return user, persona


# ═══ FR-002-27 — no write transaction across an LLM call ═══════════════════════════════════════


async def test_fr_002_27_01_turn_commits_before_generating(db):
    """The turn must not hold uncommitted writes while the model is generating."""
    user, persona = await _persona_session(db)
    session = await get_active_session(db, user.id)
    seen: list[bool] = []

    class ProbeClient(SlowClient):
        async def complete(self, messages, **kw) -> str:
            seen.append(db.in_transaction() and bool(db.new or db.dirty))
            return await super().complete(messages, **kw)

    await handle_turn(db, session, persona, "привет", ProbeClient())
    assert seen and not seen[0], "pending writes were still open during generation"


async def test_fr_002_27_02_post_turn_work_releases_the_lock(db):
    """FR-002-27: extraction/reflection must commit before their own LLM calls."""
    user, persona = await _persona_session(db)
    session = await get_active_session(db, user.id)
    pending: list[bool] = []

    class ProbeClient(SlowClient):
        async def complete(self, messages, **kw) -> str:
            pending.append(bool(db.new or db.dirty))
            return await super().complete(messages, **kw)

    await update_user_memory(db, user.id, "меня зовут Виктор", ProbeClient())
    await update_relationship(db, session, persona, ProbeClient())
    assert not any(pending), "a write transaction was held across a post-turn LLM call"


async def test_fr_002_27_03_slow_turn_does_not_starve_the_next_message(tmp_path):
    """REGRESSION (ISS-007): a second message arriving mid-turn must still persist.

    Uses a real file-backed SQLite with two independent sessions — the in-memory fixture cannot
    reproduce lock contention, which is exactly why the suite never caught this.
    """
    url = f"sqlite+aiosqlite:///{tmp_path}/t.sqlite3"
    engine = create_async_engine(url, connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    await init_models(engine)
    sm = make_sessionmaker(engine)

    async with sm() as db:
        user, persona = await _persona_session(db)
        await db.commit()
        session = await get_active_session(db, user.id)
        sid, pid, uid = session.id, persona.id, user.id

    async def turn(text: str) -> None:
        async with sm() as s:
            sess = await get_active_session(s, uid)
            p = await s.get(Persona, pid)
            await handle_turn(s, sess, p, text, SlowClient(delay=0.4))
            await s.commit()

    await asyncio.gather(turn("что ты делаешь?"), turn("скинь фото"))

    async with sm() as s:
        n = await s.scalar(select(func.count()).select_from(Message).where(
            Message.session_id == sid, Message.sender == "user"))
        assert n == 2, "one of two overlapping messages was lost to lock contention"
    await engine.dispose()


# ═══ FR-002-28 — every inbound message ends in a visible reply ═════════════════════════════════


async def test_fr_002_28_01_handler_exception_still_answers():
    """The last-resort handler answers in character when the turn blew up."""
    msg = _msg()
    event = SimpleNamespace(update=SimpleNamespace(message=msg),
                            exception=RuntimeError("anything"))
    handled = await _on_error(event)
    assert handled is True
    assert msg.answer.await_count == 1, "an unhandled error must still produce a visible reply"
    assert msg.answer.await_args.args[0]


async def test_fr_002_28_02_db_failure_still_answers():
    from sqlalchemy.exc import OperationalError
    msg = _msg()
    event = SimpleNamespace(
        update=SimpleNamespace(message=msg),
        exception=OperationalError("INSERT", {}, Exception("database is locked")))
    await _on_error(event)
    assert msg.answer.await_count == 1


async def test_fr_002_28_03_reply_is_localized():
    ru, en = _msg(uid=1), _msg(uid=2)
    en.from_user = SimpleNamespace(id=2, language_code="en")
    for m in (ru, en):
        await _on_error(SimpleNamespace(update=SimpleNamespace(message=m),
                                        exception=RuntimeError("x")))
    assert ru.answer.await_args.args[0] != en.answer.await_args.args[0]


async def test_fr_002_28_04_non_message_update_does_not_crash():
    event = SimpleNamespace(update=SimpleNamespace(message=None), exception=RuntimeError("x"))
    assert await _on_error(event) is True  # e.g. a callback query — nothing to answer, no crash


def test_fr_002_28_05_safety_net_is_registered():
    """Structural check — additive to the executing tests above.

    Asserted on the wiring source rather than by building a second Dispatcher: aiogram forbids
    attaching one Router to two dispatchers, so constructing one here breaks whichever test built
    one first. The BEHAVIOUR is proven by test_fr_002_28_01..04, which execute `_on_error`.
    """
    src = (Path(__file__).resolve().parent.parent
           / "services" / "bot" / "app.py").read_text()
    assert "dp.errors.register(_on_error)" in src


# ═══ FR-002-29 — post-turn work cannot break the turn ══════════════════════════════════════════


async def test_fr_002_29_01_extraction_failure_is_swallowed(db):
    user, _ = await _persona_session(db)
    assert await update_user_memory(db, user.id, "текст", BoomClient()) == []


async def test_fr_002_29_02_reflection_failure_is_swallowed(db):
    user, persona = await _persona_session(db)
    session = await get_active_session(db, user.id)
    await update_relationship(db, session, persona, BoomClient())  # must not raise


async def test_fr_002_29_03_turn_survives_a_broken_model(db):
    """The reply itself degrades in character rather than raising."""
    user, persona = await _persona_session(db)
    session = await get_active_session(db, user.id)
    reply = await handle_turn(db, session, persona, "привет", BoomClient())
    assert reply, "a broken model must still yield an in-character line"
