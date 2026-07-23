"""ISS-008 — she must be able to SAY what is in the photo (FR-010-19/20/21, FR-008-19, FR-012-16).

ISS-006 gave her the asset's metadata, but that metadata is written in *generation* vocabulary:
`background` was filled from `_location_phrase()` (so it just echoed `location`), and `pose` is
framing jargon ("candid high-angle selfie"). Asked "а что у тебя на фоне?", the context block
offered her `на фоне: home` — nothing visible to describe — so she filled the void herself.

The fix is a separate human-readable `scene_description`, authored in her language and carried all
the way to the prompt. Every test **executes the path** (`author_jobs`, `store_asset`,
`deliver_photo`, `recent_sends`, `handle_turn`) and asserts on what came out — never on source text.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.bot.domain.media_delivery import asset_scene, deliver_photo, recent_sends
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.models import MediaAsset, MediaKind, MediaSend, Persona
from services.bot.orchestrator import handle_turn
from services.imagegen.contract import GenerationJob, SlotMeta
from services.imagegen.prompt_author import LifeSlot, author_jobs, author_scene_description
from services.imagegen.store import store_asset
from services.imagegen.wiring import F010PromptAuthor

pytestmark = pytest.mark.asyncio

# `home` / `cafe` are the canonical location tokens `batch_planner._guess_location` emits.
EVENING_HOME = LifeSlot(activity="отдыхает после работы", location="home", time_of_day="evening")
CAFE_EN = LifeSlot(activity="coffee and a book", location="cafe", time_of_day="afternoon")

# The vocabulary that belongs to the generation request and must never reach her mouth.
JARGON = (
    "selfie", "high-angle", "camera", "signature", "negative", "prompt", "seed", "shot",
    "framing", "steps", "cfg", "picture 1", "picture 2", "photorealistic", "iphone",
)


def _job(slot: LifeSlot, language: str) -> GenerationJob:
    return author_jobs("alina", slot=slot, language=language, count=1, references=["face.png"])[0]


async def _persona(db, *, name: str = "Alina", language: str = "ru") -> Persona:
    p = Persona(name=name, profession="psychologist", age=28, language=language,
                card_description="", big_five="", timezone="Europe/Moscow")
    db.add(p)
    await db.flush()
    return p


# ── FR-010-19 — a description is authored per shot ───────────────────────────────────────────────


def test_fr_010_19_01_every_job_carries_a_description():
    """TC-FR-010-19-01 — authoring a set yields a non-empty description on every job."""
    jobs = author_jobs("alina", slot=EVENING_HOME, language="ru", count=4, references=["f.png"])

    assert len(jobs) == 4
    for job in jobs:
        assert job.slot.scene_description.strip(), "every shot must be describable"


def test_fr_010_19_02_names_visible_things_not_only_the_place():
    """TC-FR-010-19-02 — the text lists concrete objects and light, not just the location token."""
    described = _job(EVENING_HOME, "ru").slot.scene_description

    assert "отдыхает после работы" in described          # what she is doing
    assert any(w in described for w in ("диван", "торшер", "телевизор", "плед"))
    assert "свет" in described                            # how it is lit
    assert described.strip().lower() != "home"           # ISS-008: not a bare location echo


def test_fr_010_19_03_empty_slot_degrades_to_a_default():
    """TC-FR-010-19-03 — with no life state at all, a usable description is still produced."""
    for slot in (None, LifeSlot()):
        described = author_scene_description(slot, "ru")
        assert described and described.strip()
        assert "None" not in described and "{" not in described


def test_fr_010_19_04_unknown_location_still_produces_a_scene():
    """TC-FR-010-19-03 (boundary) — an unmapped location falls back instead of emitting nothing."""
    exotic = LifeSlot(activity="гуляет", location="ботанический сад", time_of_day="утро")
    described = author_scene_description(exotic, "ru")

    assert "гуляет" in described
    assert len(described) > len("гуляет") + 5  # objects/light were still appended


def test_fr_010_19_05_the_prompt_requests_what_she_will_describe():
    """TC-FR-010-19-05 — the objects she names are the objects the FRAME was asked for.

    The core ISS-008 trap: a description naming a sofa and a blanket, while the prompt's Scene
    section said only "at home", is the same confabulation moved from her mouth into our code. Both
    must be rendered from one source, so what he sees and what she says agree.
    """
    from services.imagegen.prompt_author import scene_objects

    job = _job(EVENING_HOME, "ru")

    for thing in scene_objects("home", "en").replace(" and", ",").split(","):
        assert thing.strip() in job.prompt, f"{thing!r} is described but never requested"
    for thing in scene_objects("home", "ru").replace(" и", ",").split(","):
        assert thing.strip() in job.slot.scene_description


# ── FR-010-20 — written in the persona's language ────────────────────────────────────────────────


def test_fr_010_20_01_russian_persona_gets_russian():
    """TC-FR-010-20-01 — a ru persona's description is Russian prose."""
    described = _job(EVENING_HOME, "ru").slot.scene_description

    assert any("а" <= ch <= "я" for ch in described.lower())
    assert not any(w in described.lower() for w in ("around her", "daylight", "the window"))


def test_fr_010_20_02_english_persona_gets_english():
    """TC-FR-010-20-02 — an en persona's description is English prose."""
    described = _job(CAFE_EN, "en").slot.scene_description

    assert "coffee and a book" in described
    assert not any("а" <= ch <= "я" for ch in described.lower())


def test_fr_010_20_03_unknown_language_falls_back_to_english():
    """TC-FR-010-20-02 (boundary) — an unsupported language code never yields an empty scene."""
    described = author_scene_description(CAFE_EN, "de")

    assert described.strip()
    assert "coffee and a book" in described


async def test_fr_010_20_04_wiring_passes_the_personas_language(db):
    """TC-FR-010-20-01 (integration) — the production adapter feeds PERSONA.language through.

    The bug class this pins: F-010 supports the language, but the F-011 adapter never passes it,
    so production silently authors English descriptions for a Russian girl.
    """
    from services.imagegen.batch_planner import SlotContext

    class _Refs:
        def references_for(self, persona):  # noqa: D401 - stub
            return ["face.png"]

    persona = await _persona(db, language="ru")
    ctx = SlotContext(idx=0, time_of_day="evening", activity="отдыхает после работы",
                      location="home", start_hhmm="20:00", text="вечер дома")

    shot = F010PromptAuthor(references=_Refs()).author(persona, ctx, 0)

    assert any("а" <= ch <= "я" for ch in shot.slot.scene_description.lower())


# ── FR-010-21 — no generation jargon, no appearance ──────────────────────────────────────────────


@pytest.mark.parametrize("slot,lang", [(EVENING_HOME, "ru"), (CAFE_EN, "en")])
def test_fr_010_21_01_no_generation_jargon(slot, lang):
    """TC-FR-010-21-01 — framing/technical vocabulary never appears in what she will say."""
    described = _job(slot, lang).slot.scene_description.lower()

    leaked = [w for w in JARGON if w in described]
    assert not leaked, f"generation jargon leaked into the spoken description: {leaked}"


def test_fr_010_21_02_it_is_not_the_technical_prompt():
    """TC-FR-010-21-02 — the description is authored separately, not a slice of the prompt."""
    job = _job(EVENING_HOME, "ru")

    assert job.slot.scene_description != job.prompt
    assert job.slot.scene_description not in job.prompt
    assert job.slot.scene_description != job.params.negative


def test_fr_010_21_03_it_describes_the_scene_not_her_looks():
    """TC-FR-010-21-03 — appearance stays with the reference anchors (FR-010-05)."""
    described = _job(EVENING_HOME, "ru").slot.scene_description.lower()

    for word in ("волос", "глаз", "грудь", "лицо", "фигур", "кожа"):
        assert word not in described


def test_fr_010_21_04_description_does_not_echo_the_framing_field():
    """TC-FR-010-21-01 (regression) — `pose` is jargon; the description must not be built from it."""
    job = _job(EVENING_HOME, "ru")

    assert job.slot.scene_description != job.slot.pose
    assert job.slot.pose not in job.slot.scene_description


# ── FR-008-19 — persisted with the asset ─────────────────────────────────────────────────────────


async def test_fr_008_19_01_description_is_stored_in_meta_json(db, tmp_path):
    """TC-FR-008-19-01 — storing a finished generation persists the description in meta_json."""
    from PIL import Image
    import io

    persona = await _persona(db)
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (30, 30, 40)).save(buf, format="PNG")
    job = _job(EVENING_HOME, "ru")

    asset = await store_asset(db, persona, job, buf.getvalue(), tmp_path)

    stored = json.loads(asset.meta_json)
    assert stored["scene_description"] == job.slot.scene_description
    assert stored["scene_description"].strip()


async def test_fr_008_19_02_older_payloads_without_a_description_still_store(db, tmp_path):
    """TC-FR-008-19-02 — a job authored before descriptions existed stores fine (empty, not absent)."""
    from PIL import Image
    import io

    persona = await _persona(db)
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (30, 30, 40)).save(buf, format="PNG")
    legacy = GenerationJob(
        job_key="legacy", persona_slug="alina", prompt="x",
        slot=SlotMeta(pose="candid", location="bedroom", activity="resting"),
    )

    asset = await store_asset(db, persona, legacy, buf.getvalue(), tmp_path)

    stored = json.loads(asset.meta_json)
    assert stored["scene_description"] == ""
    assert stored["location"] == "bedroom" and stored["activity"] == "resting"


def test_fr_008_19_03_description_is_not_an_echo_of_another_field():
    """TC-FR-008-19-03 — the ISS-008 defect exactly: a field that merely repeats `location`."""
    meta = json.loads(_job(EVENING_HOME, "ru").slot_meta_json())

    assert meta["scene_description"] not in (
        meta["location"], meta["background"], meta["activity"], meta["pose"], meta["time_of_day"],
    )
    assert len(meta["scene_description"]) > len(meta["location"])


# ── FR-012-16 — served at the delivery boundary ──────────────────────────────────────────────────


class RecordingChatClient:
    def __init__(self, reply: str = "ага") -> None:
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


DESCRIBED_META = {
    "scene_description": "отдыхает после работы; вокруг кровать, подушки и плед, "
                         "рядом светится экран монитора; тёплый вечерний свет лампы",
    "pose": "candid high-angle selfie",
    "background": "bedroom",
    "location": "bedroom",
    "activity": "отдыхает после работы",
    "time_of_day": "evening",
    "prompt": "candid iphone photo of a woman lying on a bed, dim bedroom",
    "seed": 424242,
}


async def _asset(db, persona, asset_id: str, meta: dict) -> MediaAsset:
    asset = MediaAsset(
        id=asset_id, persona_id=persona.id, kind=MediaKind.photo,
        intimate=False, intimacy_level=0,
        storage_ref=f"media/alina/photos/{asset_id}.png",
        meta_json=json.dumps(meta, ensure_ascii=False),
    )
    db.add(asset)
    await db.flush()
    return asset


async def test_fr_012_16_01_delivery_result_carries_the_description(db):
    """TC-FR-012-16-01 — the delivered photo's result meta includes the description."""
    user, _ = await get_or_create_user(db, telegram_id=8101, locale="ru")
    persona = await _persona(db)
    await _asset(db, persona, "MED-alina-08001", DESCRIBED_META)

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="скинь фотку",
        context={}, caption_client=RecordingChatClient("вот"), gate=FakeGate(),
    )

    assert result.meta["scene_description"] == DESCRIBED_META["scene_description"]
    assert "prompt" not in result.meta and "seed" not in result.meta


async def test_fr_012_16_02_recent_sends_carries_the_description(db):
    """TC-FR-012-16-02 — the lookback descriptor exposes it alongside the slot fields."""
    user, _ = await get_or_create_user(db, telegram_id=8102, locale="ru")
    persona = await _persona(db)
    now = datetime.now(timezone.utc)
    await _asset(db, persona, "MED-alina-08002", DESCRIBED_META)
    db.add(MediaSend(user_id=user.id, asset_id="MED-alina-08002",
                     sent_at=now - timedelta(minutes=2)))
    await db.flush()

    got = await recent_sends(db, user_id=user.id, persona_id=persona.id, now=now)

    assert got[0].scene["scene_description"] == DESCRIBED_META["scene_description"]


async def test_fr_012_16_03_context_block_states_what_is_visible(db):
    """TC-FR-012-16-03 — REGRESSION ISS-008: the block must say what is IN the frame.

    Before the fix the assembled context offered her `на фоне: bedroom` plus the framing jargon
    `поза: candid high-angle selfie` — nothing visible — so "а что у тебя на фоне?" got invented
    furniture. Now the visible scene is the line, and the jargon is gone.
    """
    user, _ = await get_or_create_user(db, telegram_id=8103, locale="ru")
    persona = await _persona(db)
    session, _ = await start_or_switch_session(db, user.id, persona.id)
    await _asset(db, persona, "MED-alina-08003", DESCRIBED_META)
    db.add(MediaSend(user_id=user.id, asset_id="MED-alina-08003",
                     sent_at=datetime.now(timezone.utc) - timedelta(minutes=2)))
    await db.flush()
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "а что у тебя на фоне", client)

    system = client.calls[0][0]["content"]
    assert "экран монитора" in system              # something she can actually name
    assert "плед" in system
    assert "candid high-angle selfie" not in system  # framing jargon never reaches her
    assert "candid iphone photo" not in system       # nor the technical prompt


async def test_fr_012_16_04_assets_without_a_description_fall_back(db):
    """TC-FR-012-16-04 — pre-ISS-008 assets still yield a block from the slot fields."""
    user, _ = await get_or_create_user(db, telegram_id=8104, locale="ru")
    persona = await _persona(db)
    session, _ = await start_or_switch_session(db, user.id, persona.id)
    legacy = {"background": "кровать и светящийся экран", "location": "спальня",
              "activity": "отдыхает", "time_of_day": "evening"}
    await _asset(db, persona, "MED-alina-08004", legacy)
    db.add(MediaSend(user_id=user.id, asset_id="MED-alina-08004",
                     sent_at=datetime.now(timezone.utc) - timedelta(minutes=2)))
    await db.flush()
    client = RecordingChatClient()

    await handle_turn(db, session, persona, "а что у тебя на фоне", client)

    system = client.calls[0][0]["content"]
    assert "кровать и светящийся экран" in system
    assert "на фоне" in system  # the labelled fallback rendering, still intact


def test_fr_012_16_05_blank_description_is_dropped_from_the_scene():
    """TC-FR-012-16-04 (edge) — an empty description never becomes an empty descriptor."""
    asset = MediaAsset(
        id="MED-x", persona_id=1, kind=MediaKind.photo, intimate=False, intimacy_level=0,
        storage_ref="media/x.png",
        meta_json=json.dumps({"scene_description": "   ", "location": "кухня"}),
    )

    assert asset_scene(asset) == {"location": "кухня"}
