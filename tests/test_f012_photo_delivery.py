"""F-012 On-Demand Photo Delivery — one runnable test per declared TC.

Maps 1:1 to `developer files/tests/F-012-on-demand-photo-delivery.md`. Selection, per-user
no-repeat, slot fallback, hot-path-free delivery, caption request, relationship pacing/gating,
intimate routing, graceful exhaustion, proactive-share pacing, send recording, and config weighting
run for real against the shared in-memory DB (conftest) with planted MEDIA_ASSET rows, a fake chat
client, and a fake F-014 gate. Benchmark-perf, human-judged context-fit, and manual/GPU user-story
TCs are explicit skips (same discipline as the rest of the suite).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from PIL import Image

import services.imagegen.backends as backends_mod
from services.bot.domain import media_delivery as md
from services.bot.domain.media_delivery import (
    DeliveryOutcome,
    MediaDeliveryConfig,
    PhotoRequestClass,
    classify_photo_request,
    deliver_photo,
    maybe_proactive_share,
    routes_to_gate,
    score_asset,
    select_asset,
)
from services.bot.models import (
    MediaAsset,
    MediaKind,
    MediaSend,
    Persona,
    Relationship,
    User,
)
from services.bot.personas_seed import persona_slug

pytestmark = pytest.mark.asyncio


# ── fakes + helpers ──────────────────────────────────────────────────────────────────────────────


class FakeCaptionClient:
    """Stands in for the chat LLM (F-002/F-003). Records prompts; returns a canned in-voice line."""

    def __init__(self, reply: str = "just got in, thinking of you 💭") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return self.reply


class FailingCaptionClient:
    async def complete(self, messages, **kwargs):
        raise RuntimeError("chat runner down")


class FakeGate:
    """Stands in for F-014's intimacy gate. Records the routed request; returns a sentinel result."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def handle_intimate_request(self, **kwargs):
        self.calls.append(kwargs)
        return {"handled_by": "F-014", **kwargs}


async def make_persona(db, name: str = "Testgirl", tz: str = "UTC") -> Persona:
    p = Persona(name=name, timezone=tz)
    db.add(p)
    await db.flush()
    return p


async def make_user(db, telegram_id: int) -> User:
    u = User(telegram_id=telegram_id)
    db.add(u)
    await db.flush()
    return u


async def set_stage(db, user: User, persona: Persona, stage: str) -> Relationship:
    rel = Relationship(user_id=user.id, persona_id=persona.id, stage=stage)
    db.add(rel)
    await db.flush()
    return rel


@pytest.fixture(autouse=True)
def _media_root(tmp_path, monkeypatch):
    """Point delivery at a temp library. Delivery now verifies the file exists before recording a
    send (F-021 NFR-021-01), so a planted asset must have one — as F-008 always leaves it."""
    monkeypatch.setattr(md, "DEFAULT_MEDIA_ROOT", tmp_path)
    return tmp_path


async def plant_asset(
    db,
    persona: Persona,
    n: int,
    *,
    meta: dict,
    intimate: bool = False,
    created_at: datetime | None = None,
) -> MediaAsset:
    slug = persona_slug(persona.name)
    med_id = f"MED-{slug}-{n:05d}"
    asset = MediaAsset(
        id=med_id,
        persona_id=persona.id,
        kind=MediaKind.photo,
        intimate=intimate,
        intimacy_level=3 if intimate else 0,
        storage_ref=f"media/{slug}/photos/{med_id}.png",
        meta_json=json.dumps(meta),
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(asset)
    await db.flush()
    target = md.DEFAULT_MEDIA_ROOT / slug / "photos" / f"{med_id}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (16, 16), (30, 30, 40)).save(target)
    return asset


def ctx(time_of_day="evening", activity="at home", location="home", mood="cozy") -> dict:
    return {"time_of_day": time_of_day, "activity": activity, "location": location, "mood": mood}


NOW = datetime.now(timezone.utc)


# ── FR-012-01 — Context-matched selection from today's archive ───────────────────────────────────


async def test_TC_FR_012_01_01_selects_matching_archive_asset(db):
    """TC-FR-012-01-01 — a photo request selects a matching archive asset."""
    p = await make_persona(db)
    u = await make_user(db, 1001)
    await plant_asset(db, p, 1, meta={"time_of_day": "morning", "activity": "gym", "location": "gym"})
    match = await plant_asset(
        db, p, 2, meta={"time_of_day": "evening", "activity": "at home", "location": "home"}
    )
    result = await deliver_photo(
        db, user_id=u.id, persona=p, request_text="send me a pic",
        context=ctx(), caption_client=FakeCaptionClient(), gate=FakeGate(), now=NOW,
    )
    assert result.outcome is DeliveryOutcome.delivered
    assert result.asset.id == match.id


async def test_TC_FR_012_01_02_meta_tags_drive_selection(db):
    """TC-FR-012-01-02 — meta tags (time/activity) drive the context score, not row order."""
    p = await make_persona(db)
    evening = await plant_asset(db, p, 1, meta={"time_of_day": "evening", "activity": "at home"})
    morning = await plant_asset(db, p, 2, meta={"time_of_day": "morning", "activity": "gym"})
    assert score_asset(evening, ctx()) > score_asset(morning, ctx())


# ── FR-012-02 — Per-user sent history, never resend (CRITICAL) ────────────────────────────────────


async def test_TC_FR_012_02_01_already_sent_excluded(db):
    """TC-FR-012-02-01 — an asset already sent is excluded on re-request."""
    p = await make_persona(db)
    u = await make_user(db, 1002)
    await set_stage(db, u, p, "Friend")
    a1 = await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    a2 = await plant_asset(db, p, 2, meta={"time_of_day": "evening"})
    cap = FakeCaptionClient()
    r1 = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                             caption_client=cap, gate=FakeGate(), now=NOW)
    r2 = await deliver_photo(db, user_id=u.id, persona=p, request_text="another?", context=ctx(),
                             caption_client=cap, gate=FakeGate(), now=NOW)
    assert {r1.asset.id, r2.asset.id} == {a1.id, a2.id}
    assert r1.asset.id != r2.asset.id


async def test_TC_FR_012_02_02_last_unseen_chosen(db):
    """TC-FR-012-02-02 — all seen but one → the last unseen is chosen."""
    p = await make_persona(db)
    u = await make_user(db, 1003)
    seen = await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    last = await plant_asset(db, p, 2, meta={"time_of_day": "evening"})
    db.add(MediaSend(user_id=u.id, asset_id=seen.id, sent_at=NOW))
    await db.flush()
    chosen = await select_asset(db, persona_id=p.id, user_id=u.id, context=ctx(), now=NOW)
    assert chosen.id == last.id


async def test_TC_FR_012_02_03_seen_filtered_in_selection(db):
    """TC-FR-012-02-03 — selection filters out every seen asset."""
    p = await make_persona(db)
    u = await make_user(db, 1004)
    a1 = await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    a2 = await plant_asset(db, p, 2, meta={"time_of_day": "evening"})
    for a in (a1, a2):
        db.add(MediaSend(user_id=u.id, asset_id=a.id, sent_at=NOW))
    await db.flush()
    chosen = await select_asset(db, persona_id=p.id, user_id=u.id, context=ctx(), now=NOW)
    assert chosen is None


# ── FR-012-03 — Prefer closest slot match with fallback ──────────────────────────────────────────


async def test_TC_FR_012_03_01_exact_slot_preferred(db):
    """TC-FR-012-03-01 — an exact slot match is preferred over a distant one."""
    p = await make_persona(db)
    u = await make_user(db, 1005)
    morning = await plant_asset(db, p, 1, meta={"time_of_day": "morning"})
    evening = await plant_asset(db, p, 2, meta={"time_of_day": "evening"})
    chosen = await select_asset(
        db, persona_id=p.id, user_id=u.id, context=ctx(time_of_day="evening", activity="", location="", mood=""),
        now=NOW,
    )
    assert chosen.id == evening.id
    assert chosen.id != morning.id


async def test_TC_FR_012_03_02_nearest_slot_fallback(db):
    """TC-FR-012-03-02 — no exact match → a sensible nearest (adjacent) slot is chosen."""
    p = await make_persona(db)
    u = await make_user(db, 1006)
    morning = await plant_asset(db, p, 1, meta={"time_of_day": "morning"})   # distance 2 from evening
    afternoon = await plant_asset(db, p, 2, meta={"time_of_day": "afternoon"})  # distance 1
    night = await plant_asset(db, p, 3, meta={"time_of_day": "night"})       # distance 1
    chosen = await select_asset(
        db, persona_id=p.id, user_id=u.id,
        context=ctx(time_of_day="evening", activity="", location="", mood=""), now=NOW,
    )
    assert chosen.id in {afternoon.id, night.id}
    assert chosen.id != morning.id


# ── FR-012-04 — No hot-path generation (CRITICAL) ────────────────────────────────────────────────


async def test_TC_FR_012_04_01_only_lookup_and_send(db, monkeypatch):
    """TC-FR-012-04-01 — served with only a lookup+send; no generation backend is built."""
    monkeypatch.setattr(backends_mod, "build_backend",
                         lambda *a, **k: (_ for _ in ()).throw(AssertionError("generation on hot path!")))
    p = await make_persona(db)
    u = await make_user(db, 1007)
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    result = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                                 caption_client=FakeCaptionClient(), gate=FakeGate(), now=NOW)
    assert result.outcome is DeliveryOutcome.delivered


async def test_TC_FR_012_04_02_no_image_model_invocation(db, monkeypatch):
    """TC-FR-012-04-02 — the delivery path references no image-model/runner symbol."""
    called = {"gen": False}
    monkeypatch.setattr(backends_mod, "build_backend",
                        lambda *a, **k: called.__setitem__("gen", True))
    p = await make_persona(db)
    u = await make_user(db, 1008)
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                        caption_client=FakeCaptionClient(), gate=FakeGate(), now=NOW)
    assert called["gen"] is False
    # The module must not even import the generation backend/runner into its namespace.
    assert not hasattr(md, "build_backend")
    assert not hasattr(md, "ImageRunner")


async def test_TC_FR_012_04_03_latency_is_db_not_generation():
    """TC-FR-012-04-03 — perf benchmark (delivery latency ≈ DB lookup) is measured out of band."""
    pytest.skip("benchmark perf TC — measured out of band, not in the unit suite")


# ── FR-012-05 — Caption in her voice ─────────────────────────────────────────────────────────────


async def test_TC_FR_012_05_01_caption_accompanies_photo(db):
    """TC-FR-012-05-01 — a delivered photo carries a persona-voice caption."""
    p = await make_persona(db)
    u = await make_user(db, 1009)
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    cap = FakeCaptionClient("home now, wish you were here 🥰")
    result = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                                 caption_client=cap, gate=FakeGate(), now=NOW)
    assert result.caption == "home now, wish you were here 🥰"
    assert cap.calls, "caption must be requested from the chat client"


async def test_TC_FR_012_05_02_caption_routes_through_chat_client(db):
    """TC-FR-012-05-02 — caption text comes from the chat client (F-002/F-003), not F-012."""
    p = await make_persona(db)
    u = await make_user(db, 1010)
    asset = await plant_asset(db, p, 1, meta={"time_of_day": "evening", "activity": "at home"})
    cap = FakeCaptionClient("x")
    await md.request_caption(cap, persona=p, asset=asset, context=ctx(), stage="Friend")
    assert len(cap.calls) == 1
    system = cap.calls[0][0]["content"]
    assert p.name in system  # the persona voice is delegated, addressed to her by name


# ── FR-012-06 — Paced/gated by relationship stage ────────────────────────────────────────────────


async def test_TC_FR_012_06_01_new_user_is_paced(db):
    """TC-FR-012-06-01 — a new user (Stranger, cap 1) is paced when spamming requests."""
    p = await make_persona(db)
    u = await make_user(db, 1011)
    await set_stage(db, u, p, "Stranger")
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    await plant_asset(db, p, 2, meta={"time_of_day": "evening"})
    cap = FakeCaptionClient()
    r1 = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                             caption_client=cap, gate=FakeGate(), now=NOW)
    r2 = await deliver_photo(db, user_id=u.id, persona=p, request_text="another?", context=ctx(),
                             caption_client=cap, gate=FakeGate(), now=NOW)
    assert r1.outcome is DeliveryOutcome.delivered
    assert r2.outcome is DeliveryOutcome.paced
    assert r2.deflection


async def test_TC_FR_012_06_02_bonded_user_is_freer(db):
    """TC-FR-012-06-02 — a bonded user (Flirting, cap 6) gets several photos freely."""
    p = await make_persona(db)
    u = await make_user(db, 1012)
    await set_stage(db, u, p, "Flirting")
    for n in range(4):
        await plant_asset(db, p, n + 1, meta={"time_of_day": "evening"})
    cap = FakeCaptionClient()
    outcomes = []
    for _ in range(4):
        r = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                                caption_client=cap, gate=FakeGate(), now=NOW)
        outcomes.append(r.outcome)
    assert all(o is DeliveryOutcome.delivered for o in outcomes)


# ── FR-012-07 — Intimate requests routed to F-014 gate ───────────────────────────────────────────


async def test_TC_FR_012_07_01_intimate_routed_to_gate(db):
    """TC-FR-012-07-01 — an intimate request routes to F-014, not the SFW archive."""
    p = await make_persona(db)
    u = await make_user(db, 1013)
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"})  # an SFW asset exists…
    gate = FakeGate()
    result = await deliver_photo(db, user_id=u.id, persona=p, request_text="send me a nude",
                                 context=ctx(), caption_client=FakeCaptionClient(), gate=gate, now=NOW)
    assert result.outcome is DeliveryOutcome.routed_to_gate
    assert result.asset is None          # …and is NOT served
    assert gate.calls and gate.calls[0]["request_text"] == "send me a nude"


async def test_TC_FR_012_07_02_sfw_path_never_serves_intimate(db):
    """TC-FR-012-07-02 — the SFW selection path never returns an intimate asset."""
    p = await make_persona(db)
    u = await make_user(db, 1014)
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"}, intimate=True)
    chosen = await select_asset(db, persona_id=p.id, user_id=u.id, context=ctx(), now=NOW)
    assert chosen is None


# ── FR-012-08 — Graceful in-voice degrade when nothing fits ──────────────────────────────────────


async def test_TC_FR_012_08_01_exhausted_archive_degrades_in_voice(db):
    """TC-FR-012-08-01 — an exhausted archive yields an in-voice deflection, no error."""
    p = await make_persona(db)
    u = await make_user(db, 1015)  # no assets planted at all
    result = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                                 caption_client=FakeCaptionClient("no good ones right now, later 😊"),
                                 gate=FakeGate(), now=NOW)
    assert result.outcome is DeliveryOutcome.deflected
    assert result.deflection and result.asset is None


async def test_TC_FR_012_08_02_degrade_never_placeholder_or_repeat(db):
    """TC-FR-012-08-02 — on no-fit, degrade text is present (never a placeholder) and records nothing."""
    p = await make_persona(db)
    u = await make_user(db, 1016)
    result = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                                 caption_client=FailingCaptionClient(), gate=FakeGate(), now=NOW)
    assert result.outcome is DeliveryOutcome.deflected
    assert result.deflection  # a safe in-voice fallback even when the chat client is down
    sends = (await db.execute(
        MediaSend.__table__.select().where(MediaSend.user_id == u.id))).all()
    assert sends == []


# ── FR-012-09 — Proactive sharing when it fits + pacing allows ───────────────────────────────────


async def test_TC_FR_012_09_01_proactive_share_when_fits(db):
    """TC-FR-012-09-01 — conversation matches her activity + pacing OK → an unprompted send."""
    p = await make_persona(db)
    u = await make_user(db, 1017)
    await set_stage(db, u, p, "Romance")
    await plant_asset(db, p, 1, meta={"time_of_day": "evening", "activity": "at home", "location": "home"})
    result = await maybe_proactive_share(
        db, user_id=u.id, persona=p, context=ctx(), caption_client=FakeCaptionClient(), now=NOW
    )
    assert result is not None and result.outcome is DeliveryOutcome.delivered


async def test_TC_FR_012_09_02_no_share_when_pacing_blocks(db):
    """TC-FR-012-09-02 — pacing not allowed → no proactive share (None)."""
    p = await make_persona(db)
    u = await make_user(db, 1018)
    await set_stage(db, u, p, "Friend")  # Friend cap = 4
    await plant_asset(db, p, 1, meta={"time_of_day": "evening", "activity": "at home", "location": "home"})
    # Fill the window to the cap so pacing blocks. Distinct assets: one asset can only ever be
    # sent to a user once (NFR-012-02, now enforced by uq_media_send_user_asset).
    for i in range(4):
        db.add(MediaSend(user_id=u.id, asset_id=f"MED-{persona_slug(p.name)}-9000{i}", sent_at=NOW))
    await db.flush()
    result = await maybe_proactive_share(
        db, user_id=u.id, persona=p, context=ctx(), caption_client=FakeCaptionClient(), now=NOW
    )
    assert result is None


# ── FR-012-10 — Delivery via Media path, send recorded ───────────────────────────────────────────


async def test_TC_FR_012_10_01_send_is_recorded(db):
    """TC-FR-012-10-01 — a completed delivery records (user, asset, time)."""
    p = await make_persona(db)
    u = await make_user(db, 1019)
    asset = await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                        caption_client=FakeCaptionClient(), gate=FakeGate(), now=NOW)
    rows = (await db.execute(
        MediaSend.__table__.select().where(MediaSend.user_id == u.id))).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.asset_id == asset.id and row.user_id == u.id and row.sent_at is not None


async def test_TC_FR_012_10_02_uses_media_path_helpers(db):
    """TC-FR-012-10-02 — delivery goes through the §3.6 Media path (store lookup + MediaSend)."""
    from services.bot.handlers.media import asset_abspath
    p = await make_persona(db)
    asset = await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    path = asset_abspath(asset, media_root="/tmp/media")
    # storage_ref (media/<slug>/photos/<id>.png) resolves under the media library root (§6.3).
    assert path.as_posix() == f"/tmp/media/{persona_slug(p.name)}/photos/{asset.id}.png"


# ── FR-012-11 — Config-driven selection/pacing/caption ───────────────────────────────────────────


async def test_TC_FR_012_11_01_config_changes_are_honored(db):
    """TC-FR-012-11-01 — edited match weights / frequency caps are honored without code change."""
    p = await make_persona(db)
    u = await make_user(db, 1020)
    await set_stage(db, u, p, "Stranger")
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    await plant_asset(db, p, 2, meta={"time_of_day": "evening"})
    # Default Stranger cap is 1; bump it to 2 by config only.
    cfg = MediaDeliveryConfig(stage_caps={**MediaDeliveryConfig().stage_caps, "Stranger": 2})
    cap = FakeCaptionClient()
    r1 = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                             caption_client=cap, gate=FakeGate(), cfg=cfg, now=NOW)
    r2 = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                             caption_client=cap, gate=FakeGate(), cfg=cfg, now=NOW)
    assert r1.outcome is DeliveryOutcome.delivered
    assert r2.outcome is DeliveryOutcome.delivered  # config raised the cap, no code change


# ── NFR-012-01 — Instant delivery (CRITICAL) ─────────────────────────────────────────────────────


async def test_TC_NFR_012_01_01_p95_under_reply_budget():
    """TC-NFR-012-01-01 — p95 latency benchmark is measured out of band."""
    pytest.skip("benchmark perf TC — measured out of band, not in the unit suite")


async def test_TC_NFR_012_01_02_served_as_lookup_no_gen(db, monkeypatch):
    """TC-NFR-012-01-02 — a request is served as a lookup+send with no generation invoked."""
    monkeypatch.setattr(backends_mod, "build_backend",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no gen on hot path")))
    p = await make_persona(db)
    u = await make_user(db, 1021)
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    result = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                                 caption_client=FakeCaptionClient(), gate=FakeGate(), now=NOW)
    assert result.outcome is DeliveryOutcome.delivered


# ── NFR-012-02 — No repeats (CRITICAL) ───────────────────────────────────────────────────────────


async def test_TC_NFR_012_02_01_no_asset_repeats(db):
    """TC-NFR-012-02-01 — across many requests, no asset repeats for the user."""
    p = await make_persona(db)
    u = await make_user(db, 1022)
    await set_stage(db, u, p, "Devoted")  # a generous cap so pacing doesn't stop us
    for n in range(6):
        await plant_asset(db, p, n + 1, meta={"time_of_day": "evening"})
    cap = FakeCaptionClient()
    seen: list[str] = []
    for _ in range(6):
        r = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                                caption_client=cap, gate=FakeGate(), now=NOW)
        if r.outcome is DeliveryOutcome.delivered:
            seen.append(r.asset.id)
    assert len(seen) == len(set(seen)) == 6


# ── NFR-012-03 — Context fit (human-judged) ──────────────────────────────────────────────────────


async def test_TC_NFR_012_03_01_context_fit_human_judged():
    """TC-NFR-012-03-01 — real context-fit quality is human-judged on a labeled sample."""
    pytest.skip("human-judged context-fit quality — reviewed manually, not automatable")


# ── NFR-012-04 — Pacing correctness ──────────────────────────────────────────────────────────────


async def test_TC_NFR_012_04_01_new_user_cannot_exceed_cap(db):
    """TC-NFR-012-04-01 — a new user cannot extract more than the per-stage cap."""
    p = await make_persona(db)
    u = await make_user(db, 1023)
    await set_stage(db, u, p, "Stranger")  # cap 1
    for n in range(5):
        await plant_asset(db, p, n + 1, meta={"time_of_day": "evening"})
    cap = FakeCaptionClient()
    delivered = 0
    for _ in range(5):
        r = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                                caption_client=cap, gate=FakeGate(), now=NOW)
        delivered += r.outcome is DeliveryOutcome.delivered
    assert delivered == 1


# ── NFR-012-05 — Graceful exhaustion ─────────────────────────────────────────────────────────────


async def test_TC_NFR_012_05_01_exhaustion_degrades_no_error(db):
    """TC-NFR-012-05-01 — an exhausted archive degrades in-voice, never raises."""
    p = await make_persona(db)
    u = await make_user(db, 1024)
    await set_stage(db, u, p, "Friend")
    a = await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    cap = FakeCaptionClient()
    r1 = await deliver_photo(db, user_id=u.id, persona=p, request_text="pic?", context=ctx(),
                             caption_client=cap, gate=FakeGate(), now=NOW)
    r2 = await deliver_photo(db, user_id=u.id, persona=p, request_text="one more?", context=ctx(),
                             caption_client=cap, gate=FakeGate(), now=NOW)
    assert r1.asset.id == a.id
    assert r2.outcome is DeliveryOutcome.deflected and r2.deflection


# ── NFR-012-06 — Per-user isolation ──────────────────────────────────────────────────────────────


async def test_TC_NFR_012_06_01_user_history_isolated(db):
    """TC-NFR-012-06-01 — user A's sent-history never affects user B's selection."""
    p = await make_persona(db)
    a_user = await make_user(db, 1025)
    b_user = await make_user(db, 1026)
    only = await plant_asset(db, p, 1, meta={"time_of_day": "evening"})
    # A already received the only asset.
    db.add(MediaSend(user_id=a_user.id, asset_id=only.id, sent_at=NOW))
    await db.flush()
    a_choice = await select_asset(db, persona_id=p.id, user_id=a_user.id, context=ctx(), now=NOW)
    b_choice = await select_asset(db, persona_id=p.id, user_id=b_user.id, context=ctx(), now=NOW)
    assert a_choice is None            # A is exhausted
    assert b_choice is not None and b_choice.id == only.id  # B is unaffected


# ── NFR-012-07 — Config-driven ───────────────────────────────────────────────────────────────────


async def test_TC_NFR_012_07_01_weighting_tunable_by_config(db):
    """TC-NFR-012-07-01 — match weighting is tunable by config without code change."""
    p = await make_persona(db)
    activity_asset = await plant_asset(db, p, 1, meta={"time_of_day": "morning", "activity": "at home"})
    time_asset = await plant_asset(db, p, 2, meta={"time_of_day": "evening", "activity": "gym"})
    context = ctx(time_of_day="evening", activity="at home", location="", mood="")
    # Default weights: activity (4) > time (3) → the activity match wins.
    assert score_asset(activity_asset, context) > score_asset(time_asset, context)
    # Reweight so time dominates — config only.
    cfg = MediaDeliveryConfig(weight_time_of_day=10.0, weight_activity=1.0)
    assert score_asset(time_asset, context, cfg) > score_asset(activity_asset, context, cfg)


# ── NFR-012-08 — Safety (SFW path never serves intimate) ─────────────────────────────────────────


async def test_TC_NFR_012_08_01_ambiguous_defaults_to_gate(db):
    """TC-NFR-012-08-01 — an ambiguous request is gate-routed and never leaks an intimate asset."""
    assert classify_photo_request("send something hotter") is PhotoRequestClass.ambiguous
    assert routes_to_gate(PhotoRequestClass.ambiguous) is True
    assert classify_photo_request("send me a selfie") is PhotoRequestClass.sfw
    p = await make_persona(db)
    u = await make_user(db, 1027)
    await plant_asset(db, p, 1, meta={"time_of_day": "evening"}, intimate=True)  # only intimate assets
    gate = FakeGate()
    result = await deliver_photo(db, user_id=u.id, persona=p, request_text="show me more",
                                 context=ctx(), caption_client=FakeCaptionClient(), gate=gate, now=NOW)
    assert result.outcome is DeliveryOutcome.routed_to_gate
    assert result.asset is None and gate.calls  # never served an intimate asset


# ── User-story acceptance (manual/GPU) ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("tc", [
    "TC-US-012-01-01", "TC-US-012-02-01", "TC-US-012-03-01", "TC-US-012-04-01", "TC-US-012-05-01",
])
async def test_user_story_acceptance_manual(tc):
    """US-012-01..05 — end-to-end/manual acceptance (real archive, real chat model, human review)."""
    pytest.skip(f"{tc}: manual/GPU end-to-end acceptance — validated by hand, not in the unit suite")
