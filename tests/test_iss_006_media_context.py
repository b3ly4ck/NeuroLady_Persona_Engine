"""ISS-006 — she must know what she just sent (F-012 FR-012-14/15, F-002 FR-002-25/26, NFR-002-13).

Live defect: Alina sent a photo of her dim bedroom (bed, a monitor screen, dark tee) and two
messages later answered "а что у тебя на фоне" with *bookshelves, a saxophone and scattered
watercolours* — a scene invented from her biography. `MEDIA_ASSET.meta_json` held the real scene the
whole time; nothing ever read it back into the prompt.

Every test here **executes the real path** — `deliver_photo`, `recent_sends`, `handle_turn`, and the
Telegram handler `on_text` — and asserts on observable results (what the chat client was actually
sent). Source-text assertions are deliberately avoided: that mistake shipped ISS-004's silent
TypeError with 766 green tests (see `tests/test_photo_path_e2e.py`).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.bot.domain import media_delivery as md
from services.bot.domain.media_delivery import (
    DeliveryOutcome,
    MediaDeliveryConfig,
    asset_scene,
    deliver_photo,
    recent_sends,
)
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import conversation as conv
from services.bot.models import MediaAsset, MediaKind, MediaSend, Persona
from services.bot.orchestrator import handle_turn

pytestmark = pytest.mark.asyncio


# ── fakes + fixtures ─────────────────────────────────────────────────────────────────────────────


class RecordingChatClient:
    """Records every message list it is called with, so we can inspect the assembled context."""

    def __init__(self, reply: str = "ага, лежу отдыхаю)") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def is_ready(self) -> bool:
        return True

    async def complete(self, messages, **kw) -> str:
        self.calls.append(messages)
        return self.reply


class FakeGate:
    async def handle_intimate_request(self, **kwargs):
        return {"handled_by": "F-014", **kwargs}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# The scene of the photo from the live report: a dim bedroom, evening, she's on the bed.
BEDROOM_META = {
    "pose": "лежит на кровати, подпёрла голову",
    "background": "кровать и светящийся экран монитора",
    "location": "спальня",
    "activity": "отдыхает после работы",
    "time_of_day": "evening",
    # provenance the generator also writes — must never leave the delivery boundary / enter a prompt
    "prompt": "candid iphone photo of a woman lying on a bed, dim bedroom, monitor glow",
    "seed": 424242,
}


async def _persona(db, *, name: str = "Alina", language: str = "ru") -> Persona:
    p = Persona(name=name, profession="psychologist", age=28, language=language,
                card_description="", big_five="", timezone="Europe/Moscow")
    db.add(p)
    await db.flush()
    return p


async def _asset(db, persona: Persona, asset_id: str, meta: dict, *,
                 intimate: bool = False) -> MediaAsset:
    asset = MediaAsset(
        id=asset_id, persona_id=persona.id, kind=MediaKind.photo,
        intimate=intimate, intimacy_level=0,
        storage_ref=f"media/alina/photos/{asset_id}.png",
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    db.add(asset)
    await db.flush()
    return asset


async def _ready_chat(db, *, telegram_id: int = 6006, language: str = "ru"):
    user, _ = await get_or_create_user(db, telegram_id=telegram_id, locale=language)
    persona = await _persona(db, language=language)
    session, _ = await start_or_switch_session(db, user.id, persona.id)
    return user, persona, session


def _system_texts(client: RecordingChatClient) -> list[str]:
    """The system message of every LLM call made — the assembled context, as actually sent."""
    return [c[0]["content"] for c in client.calls if c and c[0].get("role") == "system"]


# ── FR-012-14 — delivery returns the delivered asset's metadata ──────────────────────────────────


async def test_fr_012_14_01_delivered_result_carries_the_scene(db):
    """TC-FR-012-14-01 — a delivered photo hands its background/location/activity/pose/time back."""
    user, _ = await get_or_create_user(db, telegram_id=6101, locale="ru")
    persona = await _persona(db)
    await _asset(db, persona, "MED-alina-00001", BEDROOM_META)

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="скинь фотку",
        context={}, caption_client=RecordingChatClient("вот, лежу"), gate=FakeGate(),
    )

    assert result.outcome is DeliveryOutcome.delivered
    assert result.meta["background"] == BEDROOM_META["background"]
    assert result.meta["location"] == "спальня"
    assert result.meta["activity"] == "отдыхает после работы"
    assert result.meta["pose"] and result.meta["time_of_day"] == "evening"


async def test_fr_012_14_02_no_meta_when_nothing_was_delivered(db):
    """TC-FR-012-14-02 — deflected / gate-routed outcomes claim no scene (nothing was sent)."""
    user, _ = await get_or_create_user(db, telegram_id=6102, locale="ru")
    persona = await _persona(db)

    exhausted = await deliver_photo(  # empty archive
        db, user_id=user.id, persona=persona, request_text="скинь фотку",
        context={}, caption_client=RecordingChatClient(), gate=FakeGate(),
    )
    routed = await deliver_photo(  # intimate → F-014
        db, user_id=user.id, persona=persona, request_text="send me a nude",
        context={}, caption_client=RecordingChatClient(), gate=FakeGate(),
    )

    assert exhausted.outcome is DeliveryOutcome.deflected and exhausted.meta == {}
    assert routed.outcome is DeliveryOutcome.routed_to_gate and routed.meta == {}


async def test_fr_012_14_03_generation_provenance_is_not_exposed(db):
    """TC-FR-012-14-03 — only the five slot fields leave the boundary; prompt/seed never do."""
    user, _ = await get_or_create_user(db, telegram_id=6103, locale="ru")
    persona = await _persona(db)
    await _asset(db, persona, "MED-alina-00002", BEDROOM_META)

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="скинь фотку",
        context={}, caption_client=RecordingChatClient(), gate=FakeGate(),
    )

    assert set(result.meta) <= set(md.SCENE_FIELDS)
    assert "prompt" not in result.meta and "seed" not in result.meta


async def test_fr_012_14_04_blank_fields_are_dropped(db):
    """TC-FR-012-14-01 (edge) — empty/whitespace tags never become empty descriptors."""
    persona = await _persona(db)
    asset = await _asset(db, persona, "MED-alina-00003",
                         {"background": "  ", "location": "кухня", "activity": ""})
    assert asset_scene(asset) == {"location": "кухня"}


# ── FR-012-15 — bounded, per-user recent-sends lookup ────────────────────────────────────────────


async def test_fr_012_15_01_recent_sends_newest_first_with_scene(db):
    """TC-FR-012-15-01 — the lookup returns newest-first, each with its parsed scene + sent_at."""
    user, _ = await get_or_create_user(db, telegram_id=6201, locale="ru")
    persona = await _persona(db)
    now = _now()
    for i, (aid, minutes, location) in enumerate(
        [("MED-a-1", 180, "кафе"), ("MED-a-2", 60, "зал"), ("MED-a-3", 5, "спальня")]
    ):
        await _asset(db, persona, aid, {**BEDROOM_META, "location": location})
        db.add(MediaSend(user_id=user.id, asset_id=aid, sent_at=now - timedelta(minutes=minutes)))
    await db.flush()

    got = await recent_sends(db, user_id=user.id, persona_id=persona.id, now=now)

    assert [s.asset_id for s in got] == ["MED-a-3", "MED-a-2", "MED-a-1"]
    assert [s.scene["location"] for s in got] == ["спальня", "зал", "кафе"]
    assert all(s.sent_at.tzinfo is not None for s in got)


async def test_fr_012_15_02_bounded_by_count_and_window(db):
    """TC-FR-012-15-02 — at most the configured count, and nothing older than the window."""
    user, _ = await get_or_create_user(db, telegram_id=6202, locale="ru")
    persona = await _persona(db)
    now = _now()
    for i in range(10):  # ten sends, one per hour
        aid = f"MED-b-{i}"
        await _asset(db, persona, aid, BEDROOM_META)
        db.add(MediaSend(user_id=user.id, asset_id=aid, sent_at=now - timedelta(hours=i)))
    old_id = "MED-b-old"
    await _asset(db, persona, old_id, BEDROOM_META)
    db.add(MediaSend(user_id=user.id, asset_id=old_id, sent_at=now - timedelta(days=30)))
    await db.flush()

    default_cfg = await recent_sends(db, user_id=user.id, persona_id=persona.id, now=now)
    assert len(default_cfg) == MediaDeliveryConfig().context_recent_sends == 3
    assert old_id not in {s.asset_id for s in default_cfg}

    narrow = await recent_sends(
        db, user_id=user.id, persona_id=persona.id, now=now,
        cfg=MediaDeliveryConfig(context_recent_sends=5, context_recency_hours=2.5),
    )
    assert [s.asset_id for s in narrow] == ["MED-b-0", "MED-b-1", "MED-b-2"]  # window, not the cap

    assert await recent_sends(
        db, user_id=user.id, persona_id=persona.id, now=now,
        cfg=MediaDeliveryConfig(context_recent_sends=0),
    ) == []


async def test_fr_012_15_03_per_user_and_per_persona_isolation(db):
    """TC-FR-012-15-03 — one user's (or another persona's) sends never leak into the lookup."""
    a, _ = await get_or_create_user(db, telegram_id=6203, locale="ru")
    b, _ = await get_or_create_user(db, telegram_id=6204, locale="ru")
    alina = await _persona(db, name="Alina")
    vika = await _persona(db, name="Vika")
    now = _now()
    await _asset(db, alina, "MED-mine", {**BEDROOM_META, "location": "спальня"})
    await _asset(db, alina, "MED-his", {**BEDROOM_META, "location": "офис"})
    await _asset(db, vika, "MED-other-persona", {**BEDROOM_META, "location": "пляж"})
    db.add_all([
        MediaSend(user_id=a.id, asset_id="MED-mine", sent_at=now - timedelta(minutes=1)),
        MediaSend(user_id=b.id, asset_id="MED-his", sent_at=now - timedelta(minutes=1)),
        MediaSend(user_id=a.id, asset_id="MED-other-persona", sent_at=now - timedelta(minutes=1)),
    ])
    await db.flush()

    got = await recent_sends(db, user_id=a.id, persona_id=alina.id, now=now)
    assert [s.asset_id for s in got] == ["MED-mine"]


# ── FR-002-25 — the assembled context carries what she sent ──────────────────────────────────────


async def _send_photo_to(db, user, persona, meta=BEDROOM_META, *, asset_id="MED-sent-1",
                         minutes_ago: int = 2) -> MediaAsset:
    asset = await _asset(db, persona, asset_id, meta)
    db.add(MediaSend(user_id=user.id, asset_id=asset_id,
                     sent_at=_now() - timedelta(minutes=minutes_ago)))
    await db.flush()
    return asset


async def test_fr_002_25_01_context_contains_the_sent_photos_scene(db):
    """TC-FR-002-25-01 — after a send, the next turn's system message carries that photo's scene."""
    user, persona, session = await _ready_chat(db)
    await _send_photo_to(db, user, persona)
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "а что у тебя на фоне", client)

    system = _system_texts(client)[0]
    assert "экран монитора" in system      # the real background
    assert "спальня" in system             # location
    assert "отдыхает после работы" in system  # activity
    assert "evening" in system             # time of day
    assert "только что" in system or "мин назад" in system  # roughly when


async def test_fr_002_25_03_no_sends_means_no_block(db):
    """TC-FR-002-25-03 — a user who was never sent a photo gets no block (no empty heading)."""
    _, persona, session = await _ready_chat(db, telegram_id=6302)
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "привет", client)

    system = _system_texts(client)[0]
    assert "Фото, которые ты ему недавно отправила" not in system


async def test_fr_002_25_04_provenance_never_enters_the_prompt(db):
    """TC-FR-002-25-04 — the generation prompt/seed stored beside the scene stay out of context."""
    user, persona, session = await _ready_chat(db, telegram_id=6303)
    await _send_photo_to(db, user, persona)
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "что там у тебя", client)

    system = _system_texts(client)[0]
    assert "candid iphone photo" not in system
    assert "424242" not in system


async def test_fr_002_25_05_english_persona_gets_an_english_block(db):
    """TC-FR-002-25-01 (localization) — the block speaks the persona's language."""
    user, persona, session = await _ready_chat(db, telegram_id=6304, language="en")
    await _send_photo_to(db, user, persona,
                         {"background": "unmade bed and a glowing monitor", "location": "bedroom",
                          "time_of_day": "evening"})
    client = RecordingChatClient(reply="just chilling")

    await handle_turn(db, session, persona, "what's behind you?", client)

    system = _system_texts(client)[0]
    assert "Photos you recently sent him" in system
    assert "unmade bed and a glowing monitor" in system


# ── FR-002-26 — bounded + config-driven, single system message ───────────────────────────────────


async def test_fr_002_26_01_only_the_configured_number_of_sends(db):
    """TC-FR-002-26-01 — ten sends produce at most `context_recent_sends` lines in the block."""
    user, persona, session = await _ready_chat(db, telegram_id=6401)
    for i in range(10):
        await _send_photo_to(db, user, persona,
                             {**BEDROOM_META, "location": f"место-{i}"},
                             asset_id=f"MED-many-{i}", minutes_ago=i + 1)
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "покажи ещё", client)

    system = _system_texts(client)[0]
    mentioned = [i for i in range(10) if f"место-{i}" in system]
    assert mentioned == [0, 1, 2]  # the three newest, nothing more


async def test_fr_002_26_02_sends_outside_the_window_are_dropped(db):
    """TC-FR-002-26-02 — the only send is a week old → the block is omitted entirely."""
    user, persona, session = await _ready_chat(db, telegram_id=6402)
    await _send_photo_to(db, user, persona, asset_id="MED-stale",
                         minutes_ago=60 * 24 * 7)
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "привет", client)

    system = _system_texts(client)[0]
    assert "экран монитора" not in system
    assert "Фото, которые ты ему недавно отправила" not in system


async def test_fr_002_26_03_one_system_message_and_a_user_message(db):
    """TC-FR-002-26-03 — the block is fused in; Qwen still sees ONE system + ≥1 user message."""
    user, persona, session = await _ready_chat(db, telegram_id=6403)
    await _send_photo_to(db, user, persona, asset_id="MED-one")
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "а что у тебя на фоне", client)

    sent = client.calls[0]
    assert [m["role"] for m in sent].count("system") == 1
    assert sent[0]["role"] == "system"
    assert any(m["role"] == "user" for m in sent)
    assert sent[-1] == {"role": "user", "content": "а что у тебя на фоне"}


async def test_fr_002_26_04_config_can_widen_the_block(db):
    """TC-FR-002-26-01 (config) — raising the cap is configuration, not a code change."""
    user, persona, session = await _ready_chat(db, telegram_id=6404)
    for i in range(5):
        await _send_photo_to(db, user, persona, {**BEDROOM_META, "location": f"место-{i}"},
                             asset_id=f"MED-cfg-{i}", minutes_ago=i + 1)
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "ну как ты", client,
                      media_cfg=MediaDeliveryConfig(context_recent_sends=5))

    system = _system_texts(client)[0]
    assert all(f"место-{i}" in system for i in range(5))


# ── NFR-002-13 — media self-consistency, and the ISS-006 end-to-end regression ───────────────────


async def test_nfr_002_13_01_photo_scene_wins_over_an_unrelated_biography(db):
    """TC-NFR-002-13-01 — the scene she can describe is the one she sent, marked as what he sees."""
    user, persona, session = await _ready_chat(db, telegram_id=6501)
    await _send_photo_to(db, user, persona)
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "а что у тебя на фоне", client)

    system = _system_texts(client)[0]
    assert "это ровно то, что он видит" in system      # framed as ground truth, not flavour
    assert "не придумывай другую обстановку" in system  # the anti-confabulation instruction
    assert "экран монитора" in system


async def test_nfr_002_13_02_block_survives_full_context_assembly(db):
    """TC-NFR-002-13-02 — with memory/relationship/life/biography blocks all present, it's still in."""
    from services.bot.domain import memory as memory_domain
    from services.bot.domain.fact_extraction import MemoryOps, NewFact

    user, persona, session = await _ready_chat(db, telegram_id=6502)
    await memory_domain.apply_memory_ops(
        db, user.id, MemoryOps(add=[NewFact("work", "он работает бэкенд-разработчиком")]), None)
    await _send_photo_to(db, user, persona)
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "и как тебе вечер?", client)

    system = _system_texts(client)[0]
    assert "бэкенд-разработчиком" in system   # memory block present
    assert persona.name in system             # persona prompt present
    assert "экран монитора" in system         # …and the sent photo is still there


async def test_iss_006_regression_photo_request_then_background_question(db, tmp_path, monkeypatch):
    """REGRESSION ISS-006 (e2e, TC-FR-002-25-02) — ask for a photo, then ask what's behind her.

    Runs the real Telegram handler for both turns. The context assembled for the second turn must
    contain the delivered photo's background — the exact thing that was missing when she invented
    bookshelves and a saxophone.
    """
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(conv, "_sleep", AsyncMock())  # skip the deliberate F-003/F-012 pacing

    user, persona, _ = await _ready_chat(db, telegram_id=6600)
    photos = tmp_path / "alina" / "photos"
    photos.mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (64, 64), (40, 40, 48)).save(photos / "MED-alina-00001.png")
    await _asset(db, persona, "MED-alina-00001", BEDROOM_META)

    bot = MagicMock()
    bot.send_chat_action = AsyncMock()

    def _msg(text: str):
        m = MagicMock()
        m.from_user = SimpleNamespace(id=6600, language_code="ru")
        m.chat = SimpleNamespace(id=6600)
        m.text = text
        m.answer = AsyncMock()
        m.answer_photo = AsyncMock()
        return m

    photo_turn = _msg("скинь фотку")
    await conv.on_text(photo_turn, db, bot, RecordingChatClient("вот, лежу отдыхаю"))
    assert photo_turn.answer_photo.await_count == 1, "the photo must actually be delivered"

    sent_rows = await recent_sends(db, user_id=user.id, persona_id=persona.id)
    assert [s.asset_id for s in sent_rows] == ["MED-alina-00001"]

    client = RecordingChatClient("лежу в спальне, за спиной монитор светится")
    question = _msg("а что у тебя на фоне")
    await conv.on_text(question, db, bot, client)

    system = _system_texts(client)[0]
    assert "экран монитора" in system, "ISS-006: she must have the photo she just sent in context"
    assert "спальня" in system
