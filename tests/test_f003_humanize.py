"""F-003 human-likeness tests (pacing + chunking + comm-settings-driven style).

Maps to `TC-` ids from developer files/tests/F-003-human-like-communication.md. Because F-003 shapes
delivery/style (not content), these assert on timing bounds, chunk boundaries/counts, style
directives in the prompt, and per-persona differentiation — never on answer correctness (F-002).
"""
from __future__ import annotations

import json
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from services.bot.domain.humanize import (
    MAX_CHUNKS,
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


# ── FR-003-34 — comm_settings is the source of truth; defaults when absent/garbled ─────────────


def test_fr_003_34_01_parse_defaults_when_absent():
    """TC-FR-003-34-01 — no comm_settings → sane defaults."""
    assert parse_settings(_persona(comm_settings_json=None)) == CommSettings()


def test_fr_003_34_02_parse_from_json():
    """TC-FR-003-34-02 — knobs are read from comm_settings_json."""
    s = parse_settings(_persona(comm_settings_json=json.dumps(
        {"typing_speed": 1.5, "emoji_frequency": 0.0, "register": "literal"})))
    assert s.typing_speed == 1.5 and s.emoji_frequency == 0.0 and s.register == "literal"


def test_fr_003_34_03_parse_bad_json_falls_back():
    """TC-FR-003-34-03 — malformed comm_settings never crashes; defaults are used."""
    assert parse_settings(_persona(comm_settings_json="{not json")) == CommSettings()


# ── FR-003-09/11/14 — chunk long replies at sentence boundaries, capped, meaning preserved ─────


def test_fr_003_09_01_short_reply_single_chunk():
    """TC-FR-003-09-01 — a short reply is delivered as one message."""
    assert chunk_reply("привет, как ты?", CommSettings()) == ["привет, как ты?"]


def test_fr_003_09_02_long_reply_split_into_several():
    """TC-FR-003-09-02 — a wall of text is split into several messages."""
    long = (" ".join(f"Это предложение номер {i} про мой день." for i in range(12)))
    chunks = chunk_reply(long, CommSettings())
    assert len(chunks) > 1


def test_fr_003_14_01_chunk_count_capped():
    """TC-FR-003-14-01 — chunk count never exceeds the cap (no flooding)."""
    long = " ".join(f"Короткое предложение {i}." for i in range(40))
    chunks = chunk_reply(long, CommSettings())
    assert 1 < len(chunks) <= MAX_CHUNKS


def test_fr_003_38_01_chunks_preserve_meaning():
    """TC-FR-003-38-01 — chunks reconstruct the original text; nothing dropped or reordered."""
    long = " ".join(f"Предложение {i} тут." for i in range(15))
    chunks = chunk_reply(long, CommSettings())
    assert " ".join(chunks).split() == long.split()  # same words, same order


def test_fr_003_11_02_no_split_of_single_long_sentence():
    """TC-FR-003-11-02 — a single very long sentence is not split mid-clause."""
    one = "это очень длинное предложение без знаков конца которое тянется и тянется и тянется " * 4
    assert chunk_reply(one.strip(), CommSettings()) == [one.strip()]


# ── FR-003-01/02/06/08 — deliberate, length-scaled, jittered, capped delay ─────────────────────


def test_fr_003_06_01_delay_within_cap():
    """TC-FR-003-06-01 — the delay is always within [0.3, MAX_DELAY_S]."""
    rng = random.Random(0)
    for n in (1, 50, 500, 5000):
        d = pacing_delay("x" * n, CommSettings(), rng)
        assert 0.3 <= d <= MAX_DELAY_S


def test_fr_003_02_01_longer_text_longer_delay():
    """TC-FR-003-02-01 — a longer reply gets a longer base delay (fixed rng removes jitter noise)."""
    short = pacing_delay("hi", CommSettings(), random.Random(1))
    long = pacing_delay("word " * 40, CommSettings(), random.Random(1))
    assert long > short


def test_fr_003_05_01_faster_typist_shorter_delay():
    """TC-FR-003-05-01 — a higher typing_speed yields a shorter delay for the same text."""
    text = "word " * 6  # short enough that neither typist hits the per-chunk cap
    slow = pacing_delay(text, CommSettings(typing_speed=0.7), random.Random(2))
    fast = pacing_delay(text, CommSettings(typing_speed=1.6), random.Random(2))
    assert fast < slow


# ── FR-003-16/17/21/24 — style directives injected into the persona prompt ─────────────────────


def test_fr_003_17_02_low_emoji_directive_in_prompt():
    """TC-FR-003-17-02 — a near-zero emoji_frequency instructs the model to barely use emoji."""
    p = _persona(comm_settings_json=json.dumps({"emoji_frequency": 0.1}))
    assert "emoji very rarely" in build_system_prompt(p).lower()


def test_fr_003_21_01_prompt_asks_for_informal_register():
    """TC-FR-003-21-01 — the prompt asks for a casual, informal texting register."""
    assert "casual" in build_system_prompt(_persona()).lower()


def test_fr_003_09_03_gentle_register_directive():
    """TC-FR-003-09-03 — a 'gentle' register adds a gentle-tone directive."""
    p = _persona(comm_settings_json=json.dumps({"register": "gentle"}))
    assert "gentle" in build_system_prompt(p).lower()


# ── FR-003-09/12 — handler delivers a long reply as several ordered messages ────────────────────


async def test_fr_003_09_04_handler_delivers_chunks_in_order(monkeypatch):
    """TC-FR-003-09-04 — a long reply is sent as several messages, in order, meaning preserved."""
    monkeypatch.setattr(conv, "_sleep", AsyncMock())  # skip real pauses

    long = " ".join(f"Предложение {i} про сегодняшний день." for i in range(14))

    class LongReplyClient:
        async def is_ready(self): return True
        async def complete(self, messages, **kw): return long

    # minimal wiring: a user + persona + active session in an in-memory db
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool
    from services.bot.db import init_models, make_sessionmaker
    from services.bot.domain.sessions import start_or_switch_session
    from services.bot.domain.users import get_or_create_user

    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False}, poolclass=StaticPool)
    await init_models(engine)
    sm = make_sessionmaker(engine)
    async with sm() as db:
        user, _ = await get_or_create_user(db, 9100, "ru")
        persona = Persona(name="Alina", profession="psychologist", age=28, language="ru",
                          card_description="", big_five="")
        db.add(persona)
        await db.flush()
        await start_or_switch_session(db, user.id, persona.id)

        bot = MagicMock()
        bot.send_chat_action = AsyncMock()
        msg = MagicMock()
        msg.from_user = SimpleNamespace(id=9100, language_code="ru")
        msg.chat = SimpleNamespace(id=9100)
        msg.text = "расскажи про свой день"
        msg.answer = AsyncMock()

        await conv.on_text(msg, db, bot, LongReplyClient())

    sent = [c.args[0] for c in msg.answer.await_args_list]
    assert len(sent) > 1  # chunked
    assert " ".join(sent).split() == long.split()  # in order, meaning preserved
    await engine.dispose()


# ── FR-003-39 — reply-volume budget (texting register; no token truncation) ────────────────────


def test_fr_003_39_01_prompt_carries_volume_budget():
    """TC-FR-003-39-01 — the system prompt contains the hard sentence/word budget directives."""
    prompt = build_system_prompt(_persona())
    assert "1 to 3 short sentences" in prompt
    assert "35 words" in prompt
    assert "ONLY when he explicitly asks" in prompt
    assert "bullet points" in prompt  # no structured formatting


def test_fr_003_39_02_token_ceiling_fits_reasoning_plus_reply():
    """TC-FR-003-39-02 — the generation ceiling leaves room for the think block + a compliant
    reply (no 320-token cliff that truncated live replies mid-sentence)."""
    import inspect

    from services.bot.chat_client import ChatClient

    default = inspect.signature(ChatClient.complete).parameters["max_tokens"].default
    assert default >= 1024


# ── FR-003-40 — typing-speed-realistic pacing (word-count-based, 35-45 wpm) ────────────────────


def test_fr_003_40_01_delay_matches_human_wpm():
    """TC-FR-003-40-01 — N words ≈ N / (40wpm/60) seconds, within jitter and below the cap."""
    words = 6
    d = pacing_delay("word " * words, CommSettings(typing_speed=1.0), random.Random(7))
    expected = 0.8 + words / (40.0 / 60.0)  # ≈ 9.8s
    assert expected * 0.85 <= d <= expected * 1.15


def test_fr_003_40_02_faster_persona_types_faster():
    """TC-FR-003-40-02 — a higher typing_speed shortens the same chunk's delay proportionally."""
    text = "just a few quick words here"
    slow = pacing_delay(text, CommSettings(typing_speed=0.8), random.Random(3))
    fast = pacing_delay(text, CommSettings(typing_speed=1.6), random.Random(3))
    assert fast < slow


def test_fr_003_40_03_word_based_not_char_based():
    """TC-FR-003-40-03 — equal char length, different word counts → different delays."""
    many_words = "a b c d e f g h i j k l"          # 12 words, 23 chars
    one_word = "x" * 23                              # 1 word, 23 chars
    d_many = pacing_delay(many_words, CommSettings(), random.Random(5))
    d_one = pacing_delay(one_word, CommSettings(), random.Random(5))
    assert d_many > d_one


# ── FR-003-41 — private reasoning: prompt self-check; strip; never leak when truncated ─────────


def test_fr_003_41_01_prompt_directs_private_self_check():
    """TC-FR-003-41-01 — the prompt instructs a private pre-send check, never revealed."""
    prompt = build_system_prompt(_persona())
    assert "think privately" in prompt
    assert "Never show, quote, or mention this checking" in prompt


def test_fr_003_41_02_closed_think_block_stripped():
    """TC-FR-003-41-02 — a closed <think> block is stripped; only the visible reply remains."""
    from services.bot.orchestrator import _postprocess

    raw = "<think>чек: коротко, 1 эмодзи, в характере</think>привет, ну ты и пропал 😏"
    assert _postprocess(raw) == "привет, ну ты и пропал 😏"


def test_fr_003_41_03_truncated_think_never_leaks():
    """TC-FR-003-41-03 — an unclosed <think> (token-truncated) yields empty → caller falls back;
    raw reasoning text is never delivered."""
    from services.bot.orchestrator import _postprocess

    raw = "<think>она спросила про детство, надо ответить коротко и"
    assert _postprocess(raw) == ""


# ── NFR-003-01 — caps: ≤ MAX_DELAY_S per chunk, ≤ MAX_TOTAL_DELAY_S per reply ──────────────────


def test_nfr_003_01_01_per_chunk_delay_capped():
    """TC-NFR-003-01-01 — even a huge chunk never exceeds the per-chunk cap."""
    from services.bot.domain.humanize import MAX_TOTAL_DELAY_S  # noqa: F401 (doc anchor)

    rng = random.Random(1)
    for words in (1, 10, 50, 300):
        d = pacing_delay("word " * words, CommSettings(), rng)
        assert 0.3 <= d <= MAX_DELAY_S


def test_nfr_003_01_02_total_reply_delay_capped():
    """TC-NFR-003-01-02 — the summed deliberate delay of all chunks ≤ the total cap (+min beats)."""
    from services.bot.domain.humanize import MAX_TOTAL_DELAY_S, pacing_delays

    chunks = ["word " * 40] * MAX_CHUNKS  # every chunk alone would hit the per-chunk cap
    delays = pacing_delays(chunks, CommSettings(), random.Random(9))
    assert len(delays) == MAX_CHUNKS
    assert sum(delays) <= MAX_TOTAL_DELAY_S + 0.3 * MAX_CHUNKS  # budget + minimal beats
    assert all(d >= 0.3 for d in delays)
