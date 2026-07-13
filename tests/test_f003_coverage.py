"""F-003 supplementary coverage — automatable TC cases not covered by test_f003_humanize.py
(pacing randomness/cap, chunk boundaries + ordering, typing between chunks, prompt style directives
for emoji/register/no-lists, verbosity-driven chunking, distinct persona styles). Statistical and
manual TCs (anti-repetition rates over long chats, "feels human") stay out of scope.

Maps to `TC-` ids from developer files/tests/F-003-human-like-communication.md.
"""
from __future__ import annotations

import json
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.bot.domain.humanize import (
    MAX_DELAY_S,
    CommSettings,
    chunk_reply,
    pacing_delay,
    parse_settings,
)
from services.bot.domain.persona_prompt import build_system_prompt
from services.bot.handlers import conversation as conv
from services.bot.models import Persona


def _persona(**kw) -> Persona:
    base = dict(name="Alina", profession="psychologist", age=28, language="ru",
                card_description="", big_five="")
    base.update(kw)
    return Persona(**base)


# ── FR-003-08 / NFR-003-01 — delay randomized within a bounded band ────────────────────────────


def test_fr_003_08_01_delay_randomized_not_constant():
    """TC-FR-003-08-01 — two paced replies of the same length don't get an identical delay."""
    s = CommSettings()
    samples = {round(pacing_delay("word " * 10, s, random.Random(seed)), 4) for seed in range(15)}
    assert len(samples) > 1  # jitter makes it non-constant


def test_fr_003_08_02_delay_always_in_band():
    """TC-FR-003-08-02 / NFR-003-01 — every sampled delay stays within [0.3, MAX_DELAY_S]."""
    s = CommSettings()
    for seed in range(30):
        for n in (1, 20, 200, 4000):
            d = pacing_delay("x" * n, s, random.Random(seed))
            assert 0.3 <= d <= MAX_DELAY_S


def test_fr_003_08_03_delay_deterministic_with_fixed_rng():
    """TC-FR-003-08 — pacing is reproducible given a fixed RNG (testable/tunable)."""
    a = pacing_delay("hello there friend", CommSettings(), random.Random(7))
    b = pacing_delay("hello there friend", CommSettings(), random.Random(7))
    assert a == b


# ── FR-003-11 / FR-003-38 / NFR-003-12 — chunk boundaries, ordering, integrity ─────────────────


def test_fr_003_11_01_chunks_split_on_sentence_boundaries():
    """TC-FR-003-11-01 — a long multi-sentence reply splits only between sentences (no mid-word)."""
    text = " ".join(f"Предложение номер {i} про день." for i in range(12))
    chunks = chunk_reply(text, CommSettings())
    assert len(chunks) > 1
    for c in chunks:
        assert c == c.strip() and not c.startswith(("предложение номер",))  # never a fragment start
        # each chunk ends at sentence punctuation (last non-space char is . ! ? …)
        assert c.rstrip()[-1] in ".!?…"


def test_nfr_003_12_01_chunks_preserve_order_and_content():
    """TC-NFR-003-12-01 / FR-003-38 — chunks reconstruct the original text in order."""
    text = " ".join(f"Кусок {i} тут." for i in range(14))
    chunks = chunk_reply(text, CommSettings())
    assert " ".join(chunks).split() == text.split()


def test_fr_003_09_02_short_reply_single_chunk():
    """TC-FR-003-09-02 — a short reply is a single chunk (no needless splitting)."""
    assert chunk_reply("привет, как ты?", CommSettings()) == ["привет, как ты?"]


# ── FR-003-15 — verbosity from comm_settings drives chunking ───────────────────────────────────


def test_fr_003_15_01_low_verbosity_splits_sooner():
    """TC-FR-003-15-01 — a lower verbosity lowers the wall-of-text threshold (chunkier)."""
    text = " ".join(f"Средней длины предложение {i}." for i in range(6))
    terse = chunk_reply(text, CommSettings(verbosity=0.5))
    chatty = chunk_reply(text, CommSettings(verbosity=2.0))
    assert len(terse) >= len(chatty)


# ── FR-003-13/16/17/21 — prompt style directives (emoji / register / no lists) ─────────────────


def test_fr_003_13_01_prompt_forbids_bullet_lists():
    """TC-FR-003-13-01 — the persona prompt tells her not to use bullet lists / headings."""
    p = build_system_prompt(_persona()).lower()
    assert "bullet" in p or "lists" in p


def test_fr_003_21_01_prompt_asks_casual_register():
    """TC-FR-003-21-01 — the prompt asks for a casual, informal texting register."""
    assert "casual" in build_system_prompt(_persona()).lower()


def test_fr_003_17_01_low_vs_high_emoji_directives_differ():
    """TC-FR-003-17-01 — near-zero vs high emoji_frequency produce different emoji directives."""
    low = build_system_prompt(_persona(comm_settings_json=json.dumps({"emoji_frequency": 0.05})))
    high = build_system_prompt(_persona(comm_settings_json=json.dumps({"emoji_frequency": 0.8})))
    assert "very rarely" in low.lower()
    assert "very rarely" not in high.lower()


# ── FR-003-34/35 — settings-driven, distinct per persona ───────────────────────────────────────


def test_fr_003_35_01_two_personas_get_distinct_style_lines():
    """TC-FR-003-35-01 — two personas with different comm_settings get visibly different prompts."""
    a = build_system_prompt(_persona(
        comm_settings_json=json.dumps({"emoji_frequency": 0.05, "slang_level": 0.1, "register": "gentle"})))
    b = build_system_prompt(_persona(
        comm_settings_json=json.dumps({"emoji_frequency": 0.8, "slang_level": 0.8, "register": "casual"})))
    assert a != b


def test_fr_003_34_01_parse_settings_bad_json_defaults():
    """TC-FR-003-34-03 — malformed comm_settings never crash; defaults are used."""
    assert parse_settings(_persona(comm_settings_json="{oops")) == CommSettings()


# ── FR-003-03/10 — typing indicator per chunk (handler) ────────────────────────────────────────


async def test_fr_003_10_01_typing_shown_per_chunk(db, monkeypatch):
    """TC-FR-003-10-01 — a "typing…" action precedes each delivered chunk."""
    monkeypatch.setattr(conv, "_sleep", AsyncMock())
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from services.bot.db import init_models, make_sessionmaker
    from services.bot.domain.sessions import start_or_switch_session
    from services.bot.domain.users import get_or_create_user

    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False}, poolclass=StaticPool)
    await init_models(engine)
    sm = make_sessionmaker(engine)
    long = " ".join(f"Предложение {i} про сегодняшний день." for i in range(14))

    class LongClient:
        async def is_ready(self): return True
        async def complete(self, m, **k): return long

    async with sm() as adb:
        user, _ = await get_or_create_user(adb, 7700, "ru")
        persona = Persona(name="Alina", profession="p", age=28, language="ru",
                          card_description="", big_five="")
        adb.add(persona); await adb.flush()
        await start_or_switch_session(adb, user.id, persona.id)
        bot = MagicMock(); bot.send_chat_action = AsyncMock()
        msg = MagicMock()
        msg.from_user = SimpleNamespace(id=7700, language_code="ru")
        msg.chat = SimpleNamespace(id=7700); msg.text = "расскажи про день"; msg.answer = AsyncMock()
        await conv.on_text(msg, adb, bot, LongClient())

    n_chunks = msg.answer.await_count
    assert n_chunks > 1
    # one immediate ack + one typing per chunk
    assert bot.send_chat_action.await_count >= n_chunks
    await engine.dispose()
