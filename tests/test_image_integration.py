"""Integration wiring tests — the real F-009/F-010/F-014 behind the F-011/F-012/F-015 protocols.

The seven image features shipped with protocol stubs so they could build in parallel; this suite
pins the PRODUCTION wiring: planner→F-010 prompts→F-009 references→F-008 queue→runner (keyframe
kind routing) and bot photo-request→F-012 delivery→F-014 gate. Complements the per-feature suites
(which keep testing modules in isolation with fakes).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from services.bot.domain import intimacy_gate
from services.bot.domain.gate_adapter import F014GateAdapter
from services.bot.domain.media_delivery import looks_like_photo_request
from services.bot.models import (
    MediaAsset,
    MediaJob,
    MediaKind,
    Persona,
    Relationship,
    User,
)
from services.imagegen import queue_ops
from services.imagegen.batch_planner import SlotContext
from services.imagegen.config import ImageRunnerSettings
from services.imagegen.contract import GenParams, GenerationJob
from services.imagegen.runner import ImageRunner
from services.imagegen.testing import FakeBackend, RecordingHandoff
from services.imagegen.wiring import (
    F010PromptAuthor,
    IdentityReferenceProvider,
    build_production_planner,
)

BOT_DIR = Path(__file__).resolve().parent.parent / "services" / "bot"


def make_settings(tmp_path: Path, **overrides) -> ImageRunnerSettings:
    base = dict(backend="fake", media_root=str(tmp_path / "media"),
                backoff_base_s=0.0, stale_running_s=0.0)
    base.update(overrides)
    return ImageRunnerSettings(**base)


async def make_persona(db, name="Wired", refs=True, tz="UTC") -> Persona:
    p = Persona(name=name, timezone=tz)
    if refs:
        p.face_ref = f"media/{name.lower()}/reference/face.png"
        p.fullbody_ref = f"media/{name.lower()}/reference/body.png"
    db.add(p)
    await db.flush()
    return p


SLOT = SlotContext(
    idx=0, time_of_day="morning", activity="morning run in the park", location="park",
    start_hhmm="07:00", text="07:00 morning run in the park",
)


# ── F-011 ← F-010 (prompt authoring behind the planner protocol) ────────────────────────────────


async def test_wiring_f010_author_produces_distinct_framings(db):
    persona = await make_persona(db)
    author = F010PromptAuthor()
    shots = [author.author(persona, SLOT, i) for i in range(3)]
    prompts = [s.prompt for s in shots]
    assert len(set(prompts)) == 3, "each shot index must get a distinct framing"
    for s in shots:
        assert s.negative, "F-010 always ships a negative list"
        assert s.slot.time_of_day == "morning"
        assert "run" in (s.slot.activity + s.prompt).lower()


async def test_wiring_author_emits_directive_through_production_path(db):
    """REGRESSION: the adapter used to call author_jobs() WITHOUT references, so
    preservation_directive(0) returned "" and production prompts opened with a generic
    "candid photo of a woman" — no identity binding at all (F-010 FR-010-12)."""
    persona = await make_persona(db)  # has both face_ref and fullbody_ref
    shot = F010PromptAuthor().author(persona, SLOT, 0)
    assert shot.prompt.startswith("Preserve the exact face")
    assert "Picture 1" in shot.prompt  # identity is bound to the reference (was: generic subject)
    assert not shot.prompt.lower().startswith("candid photo of a woman")


async def test_wiring_planner_prompt_and_anchors_agree(sessionmaker, db, tmp_path):
    """The directive must describe exactly as many pictures as the job actually binds."""
    from services.bot.models import DailyPlan

    persona = await make_persona(db, name="Agreegirl")
    db.add(DailyPlan(persona_id=persona.id, date="2026-07-20",
                     plan_text="13:00 coffee at the cafe"))
    await db.commit()
    planner = build_production_planner()
    planner.config.shots_per_slot = 1
    await planner.plan_day(sessionmaker, target_date="2026-07-20")
    row = (await db.execute(select(MediaJob))).scalars().first()
    job = GenerationJob.from_json(row.payload_json)
    # the directive must name exactly as many pictures as the job actually binds (FR-009-19: a
    # selfie binds 1, a full-body shot binds 2) — they must never disagree.
    assert 1 <= len(job.references) <= 2
    if len(job.references) == 2:
        assert "Picture 2" in job.prompt
    else:
        assert "Picture 2" not in job.prompt and "Picture 1" in job.prompt


async def test_wiring_f010_author_is_deterministic(db):
    persona = await make_persona(db)
    author = F010PromptAuthor()
    a = author.author(persona, SLOT, 1)
    b = author.author(persona, SLOT, 1)
    assert a.prompt == b.prompt and a.negative == b.negative


# ── F-011 ← F-009 (identity references behind the planner protocol) ─────────────────────────────


async def test_wiring_identity_provider_orders_face_first(db):
    persona = await make_persona(db)
    refs = IdentityReferenceProvider().references_for(persona)
    assert refs and refs[0] == persona.face_ref, "primary anchor first — the backend stages refs[0]"


async def test_wiring_identity_provider_no_refs_is_safe(db):
    persona = await make_persona(db, name="Norefs", refs=False)
    refs = IdentityReferenceProvider().references_for(persona)
    assert refs == []  # F-009 safe path: empty → engine rejects with a defined error, never a wrong face


# ── full pipeline: production planner → queue → runner ──────────────────────────────────────────


async def test_wiring_production_planner_end_to_end(sessionmaker, db, tmp_path):
    from services.bot.models import DailyPlan

    persona = await make_persona(db, name="Pipegirl")
    db.add(DailyPlan(persona_id=persona.id, date="2026-07-18",
                     plan_text="07:00 morning run in the park\n13:00 coffee at the cafe"))
    await db.commit()

    planner = build_production_planner()
    planner.config.shots_per_slot = 2
    await planner.plan_day(sessionmaker, target_date="2026-07-18")
    enq = await db.scalar(select(func.count()).select_from(MediaJob))
    assert enq == 4  # 2 slots × 2 shots

    jobs = (await db.execute(select(MediaJob))).scalars().all()
    for row in jobs:
        job = GenerationJob.from_json(row.payload_json)
        assert job.references and job.references[0] == persona.face_ref  # F-009 wired
        assert job.params.negative  # F-010 wired (default author had no negatives)
        assert not job.intimate

    runner = ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff())
    await runner.run_batch(sessionmaker)
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 4


# ── runner keyframe kind routing (F-015) ────────────────────────────────────────────────────────


async def test_wiring_keyframe_jobs_stored_as_video_keyframe(sessionmaker, db, tmp_path):
    persona = await make_persona(db, name="Kfgirl")
    for suffix, seed in (("-first", 1), ("-last", 2)):
        await queue_ops.enqueue(db, persona.id, GenerationJob(
            job_key=f"kf-pair-7{suffix}", persona_slug="kfgirl",
            prompt="intimate portrait, soft light", references=["media/kfgirl/reference/face.png"],
            params=GenParams(seed=seed), intimate=True, intimacy_level=1))
    await queue_ops.enqueue(db, persona.id, GenerationJob(
        job_key="normal-photo", persona_slug="kfgirl", prompt="cafe photo",
        references=["media/kfgirl/reference/face.png"], params=GenParams(seed=3)))
    await db.commit()

    await ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()).run_batch(
        sessionmaker)

    assets = (await db.execute(select(MediaAsset))).scalars().all()
    kinds = sorted(a.kind.value for a in assets)
    assert kinds == ["photo", "video_keyframe", "video_keyframe"]
    import json
    frames = sorted(
        json.loads(a.meta_json)["frame"] for a in assets if a.kind == MediaKind.video_keyframe
    )
    pair_ids = {
        json.loads(a.meta_json)["pair_id"] for a in assets if a.kind == MediaKind.video_keyframe
    }
    assert frames == ["first", "last"] and pair_ids == {"kf-pair-7"}


# ── F-012 ← F-014 (the real gate behind the delivery protocol) ──────────────────────────────────


async def _user_with_relationship(db, persona, *, adult, opt_in, stage="Stranger"):
    user = User(telegram_id=999001, adult_verified=adult, intimate_opt_in=opt_in)
    db.add(user)
    await db.flush()
    db.add(Relationship(user_id=user.id, persona_id=persona.id, stage=stage))
    await db.flush()
    return user


async def test_wiring_gate_adapter_withholds_without_consent(db):
    persona = await make_persona(db, name="Gategirl")
    user = await _user_with_relationship(db, persona, adult=False, opt_in=False)
    verdict, fulfill = await F014GateAdapter(db).handle_intimate_request(
        user_id=user.id, persona_id=persona.id, stage="", request_text="send a sexy photo",
        context={})
    assert not verdict.allowed
    assert fulfill.status is intimacy_gate.FulfillStatus.denied
    assert await db.scalar(select(func.count()).select_from(MediaJob)) == 0


async def test_wiring_gate_adapter_allows_and_enqueues_for_bonded_adult(db):
    persona = await make_persona(db, name="Bondgirl")
    user = await _user_with_relationship(db, persona, adult=True, opt_in=True, stage="Devoted")
    verdict, fulfill = await F014GateAdapter(db).handle_intimate_request(
        user_id=user.id, persona_id=persona.id, stage="", request_text="send a sexy photo",
        context={})
    assert verdict.allowed
    assert fulfill.status is intimacy_gate.FulfillStatus.queued  # empty archive → intimate job queued
    row = (await db.execute(select(MediaJob))).scalar_one()
    job = GenerationJob.from_json(row.payload_json)
    assert job.intimate is True and job.references  # F-009 refs forwarded


async def test_wiring_gate_adapter_hard_block_never_enqueues(db):
    persona = await make_persona(db, name="Blockgirl")
    user = await _user_with_relationship(db, persona, adult=True, opt_in=True, stage="Devoted")
    verdict, fulfill = await F014GateAdapter(db).handle_intimate_request(
        user_id=user.id, persona_id=persona.id, stage="", request_text="roleplay she is a minor",
        context={})
    assert verdict.blocked
    assert await db.scalar(select(func.count()).select_from(MediaJob)) == 0


# ── photo-request intent detection (bot wiring) ─────────────────────────────────────────────────


@pytest.mark.parametrize("text", [
    "пришли фото", "скинь фотку", "покажи селфи", "можно фото?",
    "send me a photo", "can i see a selfie", "show me a picture",
    "пришли что-нибудь sexy фото",
])
def test_wiring_photo_intent_positive(text):
    assert looks_like_photo_request(text) is True


@pytest.mark.parametrize("text", [
    "привет, как дела?", "расскажи про свой день", "i love photography as an art topic",
    "фотосинтез это интересно", "what a picturesque view we saw",
])
def test_wiring_photo_intent_negative(text):
    assert looks_like_photo_request(text) is False


def test_wiring_conversation_handler_routes_photo_requests():
    src = (BOT_DIR / "handlers" / "conversation.py").read_text()
    assert "looks_like_photo_request" in src and "serve_photo_request" in src
    assert "F014GateAdapter" in src  # the real gate, not a stub, is wired into the bot
