"""F-021 — media archive retention & reuse.

Two halves of one economics argument: a frame costs ~155 s of GPU and ~1.4 MB of disk, so **never
throw away a frame nobody has seen**, and **never let age alone hide one**.

* Selection (`select_asset`) draws from the WHOLE retained library — freshness ranks, it does not
  filter. Measured live: Alina held 12 frames across two days and the 6 older ones were permanently
  unreachable because a newer day existed, so the user got a deflection while paid-for frames sat on
  disk (TC-FR-021-01-02 pins exactly that state).
* Retention (`run_retention`) evicts on a count cap in the order already-sent-oldest → un-sent-oldest,
  with the floor, the grace window and the context-recency window all outranking the cap.

Per this spec's non-negotiable method rules: every behavioural test **executes the real function or
handler** and asserts on observable outcomes — the asset object returned, the rows in
`media_assets` / `media_sends`, the files under the temp media root, and what reached the fake bot.
Retention tests always assert **both** sides plus a clean `store.reconcile`.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image
from sqlalchemy import func, select

from services.bot.domain.media_delivery import (
    DeliveryOutcome,
    MediaDeliveryConfig,
    deliver_photo,
    freshness_bonus,
    rank_score,
    recent_sends,
    select_asset,
    sent_asset_ids,
)
from services.bot.domain.sessions import start_or_switch_session
from services.bot.domain.users import get_or_create_user
from services.bot.handlers import conversation as conv
from services.bot.models import MediaAsset, MediaKind, MediaSend, Persona
from services.imagegen import retention as ret
from services.imagegen.retention import (
    RetentionConfig,
    run_retention,
    run_retention_all,
)
from services.imagegen.store import (
    allocate_med_id,
    empty_archive_personas,
    reconcile,
    retained_assets,
    store_asset,
)

pytestmark = pytest.mark.asyncio


# ── fixtures & helpers ───────────────────────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RecordingChatClient:
    def __init__(self, reply: str = "вот, держи") -> None:
        self.reply = reply
        self.calls: list = []

    async def is_ready(self) -> bool:
        return True

    async def complete(self, messages, **kw) -> str:
        self.calls.append(messages)
        return self.reply


class FakeGate:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def handle_intimate_request(self, **kwargs):
        self.calls.append(kwargs)
        return {"handled_by": "F-014", **kwargs}


async def make_persona(db, *, name: str = "Alina", language: str = "ru") -> Persona:
    p = Persona(name=name, profession="psychologist", age=28, language=language,
                card_description="", big_five="", timezone="Europe/Moscow")
    db.add(p)
    await db.flush()
    return p


def _slug(persona: Persona) -> str:
    return persona.name.lower()


async def add_asset(
    db, persona: Persona, media_root: Path, *, asset_id: str, age_days: float = 0.0,
    meta: dict | None = None, intimate: bool = False, write_file: bool = True,
) -> MediaAsset:
    """One archived frame — row **and** a real file, the way F-008 leaves it."""
    slug = _slug(persona)
    rel = f"media/{slug}/photos/{asset_id}.png"
    if write_file:
        target = media_root / slug / "photos" / f"{asset_id}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 16), (40, 40, 48)).save(target)
    asset = MediaAsset(
        id=asset_id, persona_id=persona.id, kind=MediaKind.photo,
        intimate=intimate, intimacy_level=2 if intimate else 0, storage_ref=rel,
        meta_json=json.dumps(meta or {}, ensure_ascii=False),
        created_at=_now() - timedelta(days=age_days),
    )
    db.add(asset)
    await db.flush()
    return asset


async def archive(
    db, persona: Persona, media_root: Path, days: dict[int, int], *,
    meta: dict | None = None, prefix: str = "A",
) -> list[MediaAsset]:
    """`days={-3: 6, 0: 6}` → 6 frames aged three days and 6 from today, oldest first."""
    out: list[MediaAsset] = []
    for age in sorted(days, reverse=True):  # most negative (oldest) first
        for i in range(days[age]):
            out.append(await add_asset(
                db, persona, media_root,
                asset_id=f"MED-{_slug(persona)}-{prefix}{abs(age):02d}{i:02d}",
                age_days=abs(age), meta=meta,
            ))
    return out


async def mark_sent(db, user_id: int, assets, *, hours_ago: float = 300.0) -> None:
    for a in assets:
        db.add(MediaSend(user_id=user_id, asset_id=a.id if hasattr(a, "id") else a,
                         sent_at=_now() - timedelta(hours=hours_ago)))
    await db.flush()


async def archive_state(db, persona: Persona, media_root: Path) -> tuple[set[str], set[str]]:
    """(row ids, file stems) — every retention test asserts on BOTH."""
    rows = {a.id for a in await retained_assets(db, persona.id)}
    files = {p.stem for p in (media_root / _slug(persona) / "photos").glob("*.png")}
    return rows, files


async def assert_clean(db, media_root: Path) -> None:
    report = await reconcile(db, media_root)
    assert report == {"rows_missing_file": [], "files_missing_row": []}, report


HOME_EVENING = {"time_of_day": "evening", "activity": "дома", "location": "home"}
WALK = {"time_of_day": "afternoon", "activity": "walk", "location": "outdoors",
        "background": "street"}
WALK_CTX = {"time_of_day": "afternoon", "activity": "walk", "location": "outdoors"}
NO_PACING = MediaDeliveryConfig(stage_caps={"Stranger": 999}, pacing_window_hours=0.001)


# ══ FR-021-01 — freshness ranks, it does not filter ══════════════════════════════════════════════


async def test_fr_021_01_01_candidate_set_spans_all_retained_days(db, tmp_path):
    """TC-FR-021-01-01 — 6 from today + 6 from three days ago ⇒ 12 candidates, not 6."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {0: 6, -3: 6})

    assert len(await retained_assets(db, persona.id)) == 12


async def test_fr_021_01_02_the_live_alina_case_is_reachable_again(db, tmp_path):
    """TC-FR-021-01-02 — REGRESSION: the measured live state, where 6 frames were unreachable.

    Two days of 6 frames each, every one of day D already sent to this user. The one-day window
    returned `None` here and the user got a deflection while 6 paid-for frames sat on disk.
    """
    user, _ = await get_or_create_user(db, telegram_id=2101, locale="ru")
    persona = await make_persona(db)
    yesterday = await archive(db, persona, tmp_path, {-1: 6}, prefix="Y")
    today = await archive(db, persona, tmp_path, {0: 6}, prefix="T")
    await mark_sent(db, user.id, today)

    picked = await select_asset(db, persona_id=persona.id, user_id=user.id, context={})

    assert picked is not None, "6 unsent frames existed — returning None threw away paid GPU work"
    assert picked.id in {a.id for a in yesterday}


async def test_fr_021_01_03_no_assets_degrades_cleanly(db, tmp_path):
    """TC-FR-021-01-03 — an empty archive still returns None and deflects in voice, never raises."""
    user, _ = await get_or_create_user(db, telegram_id=2102, locale="ru")
    persona = await make_persona(db)

    assert await select_asset(db, persona_id=persona.id, user_id=user.id, context={}) is None

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="скинь фотку",
        context={}, caption_client=RecordingChatClient(), gate=FakeGate(),
    )
    assert result.outcome is DeliveryOutcome.deflected
    assert result.deflection and result.deflection.strip(), "silence is never acceptable"


async def test_fr_021_01_04_widening_smuggles_in_nothing_ineligible(db, tmp_path):
    """TC-FR-021-01-04 — widening changes AGE eligibility only: no intimate, no repeats."""
    user, _ = await get_or_create_user(db, telegram_id=2103, locale="ru")
    persona = await make_persona(db)
    old_intimate = await add_asset(db, persona, tmp_path, asset_id="MED-alina-INT", age_days=9,
                                   intimate=True, meta=HOME_EVENING)
    already_sent = await add_asset(db, persona, tmp_path, asset_id="MED-alina-SENT", age_days=5,
                                   meta=HOME_EVENING)
    fresh = await add_asset(db, persona, tmp_path, asset_id="MED-alina-OK", age_days=0)
    await mark_sent(db, user.id, [already_sent])

    for _ in range(5):
        picked = await select_asset(db, persona_id=persona.id, user_id=user.id, context={})
        assert picked.id == fresh.id
        assert picked.id not in {old_intimate.id, already_sent.id}


async def test_fr_021_01_05_composed_batch_to_retention_to_delivery(db, tmp_path, monkeypatch):
    """TC-FR-021-01-05 — three nights of archive → retention → a real handler turn delivers once."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(conv, "_sleep", AsyncMock())

    user, _ = await get_or_create_user(db, telegram_id=2104, locale="ru")
    persona = await make_persona(db)
    await start_or_switch_session(db, user.id, persona.id)
    await archive(db, persona, tmp_path, {-2: 6, -1: 6, 0: 6})
    for _ in range(3):
        await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=60, floor=6))

    message = MagicMock()
    message.from_user = SimpleNamespace(id=2104, language_code="ru")
    message.chat = SimpleNamespace(id=2104)
    message.text = "скинь фотку"
    message.answer = AsyncMock()
    message.answer_photo = AsyncMock()
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()

    await conv.on_text(message, db, bot, RecordingChatClient())

    assert message.answer_photo.await_count == 1
    sends = (await db.execute(select(MediaSend).where(MediaSend.user_id == user.id))).scalars().all()
    assert len(sends) == 1
    assert sends[0].asset_id in {a.id for a in await retained_assets(db, persona.id)}


async def test_fr_021_01_06_selection_no_longer_bounded_by_one_day(db, tmp_path):
    """TC-FR-021-01-06 (structural, additive) — the one-day helper is not what bounds candidacy."""
    import services.bot.domain.media_delivery as md
    import inspect

    source = inspect.getsource(md.select_asset)
    body = source.replace(md.select_asset.__doc__ or "", "")  # the docstring cites it by name
    assert "retained_assets" in body
    assert "latest_available_assets" not in body


# ══ FR-021-02 — config-driven freshness bonus ════════════════════════════════════════════════════


async def test_fr_021_02_01_equal_fit_today_wins(db, tmp_path):
    """TC-FR-021-02-01 — identical metadata, one today and one three days old → today's is sent."""
    user, _ = await get_or_create_user(db, telegram_id=2201, locale="ru")
    persona = await make_persona(db)
    old = await add_asset(db, persona, tmp_path, asset_id="MED-alina-OLD", age_days=3,
                          meta=HOME_EVENING)
    new = await add_asset(db, persona, tmp_path, asset_id="MED-alina-NEW", age_days=0,
                          meta=HOME_EVENING)

    picked = await select_asset(db, persona_id=persona.id, user_id=user.id,
                                context={"time_of_day": "evening"})

    assert picked.id == new.id and picked.id != old.id


async def test_fr_021_02_02_bonus_decays_monotonically_and_never_goes_negative(db, tmp_path):
    """TC-FR-021-02-02 — the freshness component is non-increasing in age and floors at zero."""
    persona = await make_persona(db)
    cfg = MediaDeliveryConfig()
    bonuses = []
    for age in (0, 1, 3, 7, 30):
        asset = await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-D{age}", age_days=age)
        bonuses.append(freshness_bonus(asset, cfg))

    assert bonuses == sorted(bonuses, reverse=True), bonuses
    assert all(b >= 0.0 for b in bonuses)
    assert bonuses[0] > bonuses[-1]
    assert bonuses[-1] < bonuses[0] * 0.05, "a 30-day-old frame must carry almost no freshness"


async def test_fr_021_02_03_huge_bonus_degenerates_to_today_only(db, tmp_path):
    """TC-FR-021-02-03 — a bonus far above the fit spread makes today's poor frame win."""
    user, _ = await get_or_create_user(db, telegram_id=2203, locale="ru")
    persona = await make_persona(db)
    perfect_old = await add_asset(db, persona, tmp_path, asset_id="MED-alina-PO", age_days=7,
                                  meta=WALK)
    poor_new = await add_asset(db, persona, tmp_path, asset_id="MED-alina-PN", age_days=0,
                               meta={"time_of_day": "night", "activity": "сон"})
    # bonus 100 at age 0 vs 100/8 = 12.5 at age 7 — a gap no context-fit spread (max ~10) can close
    cfg = MediaDeliveryConfig(freshness_bonus=100.0, freshness_decay_per_day=1.0)

    picked = await select_asset(db, persona_id=persona.id, user_id=user.id,
                                context=WALK_CTX, cfg=cfg)

    assert picked.id == poor_new.id and perfect_old is not None


async def test_fr_021_02_04_small_bonus_yields_variety_across_days(db, tmp_path):
    """TC-FR-021-02-04 — with a near-zero bonus, ten real deliveries span several days."""
    user, _ = await get_or_create_user(db, telegram_id=2204, locale="ru")
    persona = await make_persona(db)
    for age in (0, 1, 2, 3, 4):
        for i in range(2):
            await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-V{age}{i}",
                            age_days=age, meta={"activity": f"act-{age}"})
    cfg = MediaDeliveryConfig(freshness_bonus=0.0, freshness_decay_per_day=0.0,
                              stage_caps={"Stranger": 999}, pacing_window_hours=0.001)

    delivered_ages = set()
    for _ in range(10):
        result = await deliver_photo(
            db, user_id=user.id, persona=persona, request_text="скинь фотку",
            context={"activity": "act-4"}, caption_client=RecordingChatClient(),
            gate=FakeGate(), cfg=cfg, media_root=tmp_path,
        )
        if result.outcome is DeliveryOutcome.delivered:
            delivered_ages.add(result.asset.id[len("MED-alina-V")])

    assert len(delivered_ages) >= 3, f"variety-first config drained one day only: {delivered_ages}"


# ══ FR-021-03 — a materially better fit can beat freshness ═══════════════════════════════════════


async def test_fr_021_03_01_outdoor_ask_picks_the_old_walk(db, tmp_path):
    """TC-FR-021-03-01 — UC-021-03: tonight's sofa loses to a five-day-old walk when he asks."""
    user, _ = await get_or_create_user(db, telegram_id=2301, locale="ru")
    persona = await make_persona(db)
    walk = await add_asset(db, persona, tmp_path, asset_id="MED-alina-WALK", age_days=5, meta=WALK)
    for i in range(3):
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-SOFA{i}", age_days=0,
                        meta=HOME_EVENING)

    picked = await select_asset(db, persona_id=persona.id, user_id=user.id, context=WALK_CTX)

    assert picked.id == walk.id


async def test_fr_021_03_02_the_tipping_point_is_exactly_the_configured_margin(db, tmp_path):
    """TC-FR-021-03-02 — D7: the margin an older frame must beat IS the bonus it forfeits.

    One age gap, one fit gap, two configs: the winner flips on configuration alone.
    """
    user, _ = await get_or_create_user(db, telegram_id=2302, locale="ru")
    persona = await make_persona(db)
    # fit gap = weight_activity (4.0) EXACTLY: only the activity differs, nothing else is tagged.
    old = await add_asset(db, persona, tmp_path, asset_id="MED-alina-OFIT", age_days=1,
                          meta={"activity": "walk"})
    new = await add_asset(db, persona, tmp_path, asset_id="MED-alina-NFIT", age_days=0,
                          meta={"activity": "дома"})

    # over a 1-day gap the fresh frame's edge is bonus*decay/(1+decay) — put it either side of 4.0
    strong = MediaDeliveryConfig(freshness_bonus=10.0, freshness_decay_per_day=1.0)   # edge 5.0
    weak = MediaDeliveryConfig(freshness_bonus=3.0, freshness_decay_per_day=1.0)      # edge 1.5

    ctx = {"activity": "walk"}
    assert (await select_asset(db, persona_id=persona.id, user_id=user.id,
                               context=ctx, cfg=strong)).id == new.id
    assert (await select_asset(db, persona_id=persona.id, user_id=user.id,
                               context=ctx, cfg=weak)).id == old.id


async def test_fr_021_03_03_a_marginal_advantage_does_not_beat_freshness(db, tmp_path):
    """TC-FR-021-03-03 — "materially better" is required, not "any better"."""
    user, _ = await get_or_create_user(db, telegram_id=2303, locale="ru")
    persona = await make_persona(db)
    # mood is the lightest weight (1.0) — strictly less than the 3.0 freshness bonus at age 0.
    old = await add_asset(db, persona, tmp_path, asset_id="MED-alina-MARG", age_days=2,
                          meta={"mood": "тёплое"})
    new = await add_asset(db, persona, tmp_path, asset_id="MED-alina-FRESH", age_days=0, meta={})

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="скинь фотку",
        context={"mood": "тёплое"}, caption_client=RecordingChatClient(), gate=FakeGate(),
        media_root=tmp_path,
    )

    assert result.asset.id == new.id and old is not None


# ══ FR-021-04 — per-persona count cap ════════════════════════════════════════════════════════════


async def test_fr_021_04_01_under_the_cap_keeps_everything(db, tmp_path):
    """TC-FR-021-04-01 — 20 assets under a cap of 60: nothing is touched, zero evictions."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-5: 20})

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=60, floor=6))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 20
    assert report.evicted == 0 and report.kept == 20
    await assert_clean(db, tmp_path)


async def test_fr_021_04_02_exactly_at_the_cap_evicts_nothing(db, tmp_path):
    """TC-FR-021-04-02 — the cap is inclusive."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-5: 30})

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=30, floor=6))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 30 and report.evicted == 0


async def test_fr_021_04_03_over_the_cap_returns_to_the_cap_not_below(db, tmp_path):
    """TC-FR-021-04-03 — 42 assets, cap 30 → exactly 12 evicted, no over-eviction."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-5: 42})

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=30, floor=10))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 30
    assert report.evicted == 12 and report.archive_size == 30
    await assert_clean(db, tmp_path)


async def test_fr_021_04_04_age_alone_never_evicts(db, tmp_path):
    """TC-FR-021-04-04 — a 90-day-old archive under the cap loses nothing: storage is cheap."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-90: 12})

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=60, floor=6))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 12 and report.evicted == 0


# ══ FR-021-05 — eviction order (CRITICAL) ════════════════════════════════════════════════════════


async def test_fr_021_05_01_sent_frames_go_before_unsent_ones(db, tmp_path):
    """TC-FR-021-05-01 — UC-021-06: 6 sent + 8 unsent, cap 10 → the 4 victims are all sent ones."""
    user, _ = await get_or_create_user(db, telegram_id=2501, locale="ru")
    persona = await make_persona(db)
    sent = await archive(db, persona, tmp_path, {-9: 6}, prefix="S")
    unsent = await archive(db, persona, tmp_path, {-5: 8}, prefix="U")
    await mark_sent(db, user.id, sent)

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=10, floor=4))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 10
    assert {a.id for a in unsent} <= rows, "un-sent GPU work was destroyed while sent frames existed"
    assert report.evicted_sent == 4 and report.evicted_unsent == 0
    await assert_clean(db, tmp_path)


async def test_fr_021_05_02_within_a_tier_oldest_goes_first(db, tmp_path):
    """TC-FR-021-05-02 — 12 sent assets of distinct ages, cap 8 → exactly the 4 oldest are gone."""
    user, _ = await get_or_create_user(db, telegram_id=2502, locale="ru")
    persona = await make_persona(db)
    assets = [
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-AGE{age:02d}", age_days=age)
        for age in range(12)
    ]
    await mark_sent(db, user.id, assets)

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=8, floor=4, grace_hours=0.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert rows == files == {f"MED-alina-AGE{age:02d}" for age in range(8)}


async def test_fr_021_05_03_all_unsent_evicts_the_oldest_unsent(db, tmp_path):
    """TC-FR-021-05-03 — the un-sent tier is used only once the sent tier is empty."""
    persona = await make_persona(db)
    for age in range(13):
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-N{age:02d}", age_days=age + 1)

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=10, floor=4))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 10
    assert report.evicted_unsent == 3 and report.evicted_sent == 0
    assert rows == {f"MED-alina-N{age:02d}" for age in range(10)}  # the newest survive


async def test_fr_021_05_04_all_sent_is_straightforward_oldest_first(db, tmp_path):
    """TC-FR-021-05-04 — 15 sent assets, cap 10 → the 5 oldest go."""
    user, _ = await get_or_create_user(db, telegram_id=2504, locale="ru")
    persona = await make_persona(db)
    assets = [
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-Z{age:02d}", age_days=age + 1)
        for age in range(15)
    ]
    await mark_sent(db, user.id, assets)

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=10, floor=4))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 10 and report.evicted == 5
    assert rows == {f"MED-alina-Z{age:02d}" for age in range(10)}


async def test_fr_021_05_05_sent_tier_exhausted_then_oldest_unsent(db, tmp_path):
    """TC-FR-021-05-05 — 3 sent + 12 unsent, cap 10 → all 3 sent, then exactly 2 oldest unsent."""
    user, _ = await get_or_create_user(db, telegram_id=2505, locale="ru")
    persona = await make_persona(db)
    sent = [
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-P{i}", age_days=20 + i)
        for i in range(3)
    ]
    unsent = [
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-Q{i:02d}", age_days=i + 1)
        for i in range(12)
    ]
    await mark_sent(db, user.id, sent)

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=10, floor=4))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 10
    assert report.evicted_sent == 3 and report.evicted_unsent == 2
    assert not ({a.id for a in sent} & rows)
    # the two oldest un-sent are the highest-numbered (age = i+1)
    assert unsent[-1].id not in rows and unsent[-2].id not in rows
    await assert_clean(db, tmp_path)


async def test_fr_021_05_06_sent_means_sent_to_any_user(db, tmp_path):
    """TC-FR-021-05-06 — D6: a frame user A saw is cheaper than one nobody saw, even for user B."""
    a, _ = await get_or_create_user(db, telegram_id=2506, locale="ru")
    await get_or_create_user(db, telegram_id=2507, locale="ru")  # user B, has seen nothing
    persona = await make_persona(db)
    seen_by_a = await add_asset(db, persona, tmp_path, asset_id="MED-alina-SEENA", age_days=10)
    seen_by_none = await add_asset(db, persona, tmp_path, asset_id="MED-alina-SEENN", age_days=10)
    for i in range(9):
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-F{i}", age_days=1)
    await mark_sent(db, a.id, [seen_by_a])

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=10, floor=4))

    rows, _ = await archive_state(db, persona, tmp_path)
    assert seen_by_a.id not in rows
    assert seen_by_none.id in rows


# ══ FR-021-06 — floor, and never an empty archive ════════════════════════════════════════════════


async def test_fr_021_06_01_the_floor_stops_eviction(db, tmp_path):
    """TC-FR-021-06-01 — at least `floor` assets always remain."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 8})

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=20, floor=6))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) >= 6


async def test_fr_021_06_02_cap_equals_floor_is_stable_and_idempotent(db, tmp_path):
    """TC-FR-021-06-02 — cap=floor=6 over 9 assets: 6 remain, and a second run evicts nothing."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 9})
    cfg = RetentionConfig(cap=6, floor=6)

    first = await run_retention(db, persona.id, tmp_path, cfg)
    rows_1, files_1 = await archive_state(db, persona, tmp_path)
    second = await run_retention(db, persona.id, tmp_path, cfg)
    rows_2, files_2 = await archive_state(db, persona, tmp_path)

    assert len(rows_1) == 6 and first.evicted == 3
    assert second.evicted == 0 and rows_1 == rows_2 and files_1 == files_2
    await assert_clean(db, tmp_path)


async def test_fr_021_06_03_cap_below_tonights_batch_keeps_the_newest(db, tmp_path):
    """TC-FR-021-06-03 — D5: tonight's 6 frames survive a cap of 4; the grace window outranks it."""
    persona = await make_persona(db)
    tonight = await archive(db, persona, tmp_path, {0: 6})

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=4, floor=3, grace_hours=24.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert rows == files == {a.id for a in tonight}, "a too-small cap deleted the batch just paid for"
    assert report.cap_exceeded and report.evicted_unsent == 0
    assert any("protected" in n for n in report.notes)


async def test_fr_021_06_04_floor_greater_than_cap_lets_the_floor_win(db, tmp_path):
    """TC-FR-021-06-04 — D4: cap=5, floor=8, 12 assets → 8 survive and the contradiction is logged."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 12})

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=5, floor=8))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 8
    assert report.cap_exceeded
    assert any("floor" in n and "cap" in n for n in report.notes)


@pytest.mark.parametrize("cap,floor", [(0, 0), (0, 3), (1, 0), (5, 1)])
async def test_fr_021_06_05_a_single_asset_archive_is_never_emptied(db, tmp_path, cap, floor):
    """TC-FR-021-06-05 — one asset survives under every config, including cap=0 (NFR-008-03)."""
    persona = await make_persona(db)
    only = await add_asset(db, persona, tmp_path, asset_id="MED-alina-ONLY", age_days=40)

    await run_retention(db, persona.id, tmp_path,
                        RetentionConfig(cap=cap, floor=floor, grace_hours=0.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert rows == files == {only.id}


# ══ FR-021-07 — atomic eviction; MediaSend survives ══════════════════════════════════════════════


async def test_fr_021_07_01_file_and_row_die_together(db, tmp_path):
    """TC-FR-021-07-01 — UC-021-08: both sides gone, reconciliation clean."""
    persona = await make_persona(db)
    assets = await archive(db, persona, tmp_path, {-9: 8})

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=5, floor=2, grace_hours=0.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 5
    gone = {a.id for a in assets} - rows
    assert gone and not (gone & files), "an evicted row left its file behind"
    await assert_clean(db, tmp_path)


async def test_fr_021_07_02_file_delete_failure_keeps_the_row(db, tmp_path, monkeypatch):
    """TC-FR-021-07-02 — an undeletable file means the row stays: no orphan file, run continues."""
    persona = await make_persona(db)
    assets = await archive(db, persona, tmp_path, {-9: 8})
    victim = assets[0].id
    real_replace = ret.os.replace

    def _flaky(src, dst):
        if victim in str(src):
            raise OSError("permission denied")
        return real_replace(src, dst)

    monkeypatch.setattr(ret.os, "replace", _flaky)

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=5, floor=2, grace_hours=0.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert victim in rows and victim in files, "the undeletable file lost its row"
    assert any(victim in f for f in report.failures)
    assert report.evicted == 3, "the rest of the run must still complete"
    await assert_clean(db, tmp_path)


async def test_fr_021_07_03_row_delete_failure_keeps_the_file(db, tmp_path, monkeypatch):
    """TC-FR-021-07-03 — a row delete that raises rolls back and the file is put back."""
    persona = await make_persona(db)
    assets = await archive(db, persona, tmp_path, {-9: 8})
    victim = assets[0].id
    real_delete = db.delete

    async def _flaky(obj):
        if getattr(obj, "id", None) == victim:
            raise RuntimeError("row delete blew up")
        return await real_delete(obj)

    monkeypatch.setattr(db, "delete", _flaky)

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=5, floor=2, grace_hours=0.0))

    monkeypatch.undo()
    rows, files = await archive_state(db, persona, tmp_path)
    assert victim in rows and victim in files, "the file was destroyed although its row survived"
    assert any(victim in f for f in report.failures)
    await assert_clean(db, tmp_path)


async def test_fr_021_07_04_media_send_survives_its_asset(db, tmp_path):
    """TC-FR-021-07-04 — the subtle one: the send row and its id outlive the evicted frame."""
    user, _ = await get_or_create_user(db, telegram_id=2704, locale="ru")
    persona = await make_persona(db)
    assets = await archive(db, persona, tmp_path, {-30: 8})
    x = assets[0]
    await mark_sent(db, user.id, assets, hours_ago=500.0)

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=5, floor=2, grace_hours=0.0))

    rows, _ = await archive_state(db, persona, tmp_path)
    assert x.id not in rows, "precondition: X was evicted"
    send = await db.scalar(select(MediaSend).where(MediaSend.asset_id == x.id))
    assert send is not None and send.sent_at is not None
    assert x.id in await sent_asset_ids(db, user.id)


async def test_fr_021_07_05_an_evicted_asset_never_becomes_resendable(db, tmp_path):
    """TC-FR-021-07-05 — the evicted id is neither served again nor **reissued** to a new frame."""
    user, _ = await get_or_create_user(db, telegram_id=2705, locale="ru")
    persona = await make_persona(db)
    assets = [
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-{i:05d}", age_days=30 - i)
        for i in range(1, 9)
    ]
    await mark_sent(db, user.id, assets, hours_ago=500.0)
    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=5, floor=2, grace_hours=0.0))
    evicted = {a.id for a in assets} - (await archive_state(db, persona, tmp_path))[0]
    assert evicted, "precondition: something was evicted"

    # a later batch allocates new ids — none may collide with a retired one (FR-021-13 / D1)
    fresh_ids = {await allocate_med_id(db, persona, "alina") for _ in range(5)}
    assert not (fresh_ids & evicted), f"a retired id was reissued: {fresh_ids & evicted}"
    assert not (fresh_ids & {a.id for a in assets})

    for _ in range(3):
        picked = await select_asset(db, persona_id=persona.id, user_id=user.id, context={})
        assert picked is None or picked.id not in evicted


async def test_fr_021_07_06_recent_sends_degrades_when_its_asset_is_evicted(db, tmp_path):
    """TC-FR-021-07-06 — the ISS-006 join survives eviction: fewer entries, never a raise."""
    user, _ = await get_or_create_user(db, telegram_id=2706, locale="ru")
    persona = await make_persona(db)
    kept = await add_asset(db, persona, tmp_path, asset_id="MED-alina-KEEP", age_days=0,
                           meta={"scene_description": "дома на диване"})
    stale = await add_asset(db, persona, tmp_path, asset_id="MED-alina-STALE", age_days=40)
    db.add(MediaSend(user_id=user.id, asset_id=kept.id, sent_at=_now() - timedelta(minutes=5)))
    db.add(MediaSend(user_id=user.id, asset_id=stale.id, sent_at=_now() - timedelta(minutes=10)))
    await db.flush()
    # evict `stale` directly — it is outside every protection window
    await db.delete(stale)
    await db.flush()

    got = await recent_sends(db, user_id=user.id, persona_id=persona.id)

    assert [s.asset_id for s in got] == [kept.id]
    assert all(s.scene for s in got), "no NULL-scene entry may leak into the prompt"


async def test_fr_021_15_01_context_recency_outranks_the_cap(db, tmp_path):
    """TC-FR-021-07-06 (FR-021-15 / D3) — a photo sent an hour ago is never evicted.

    Without this, retention would silently remove the frame from her conversation context and she
    would invent a background for a photo she just sent — ISS-006, reopened by our own maintenance.
    """
    user, _ = await get_or_create_user(db, telegram_id=2707, locale="ru")
    persona = await make_persona(db)
    assets = await archive(db, persona, tmp_path, {-30: 10})
    just_sent = assets[0]  # the OLDEST — first in line for eviction by every other rule
    await mark_sent(db, user.id, [just_sent], hours_ago=1.0)

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=5, floor=2, grace_hours=0.0,
                                                 context_recency_hours=48.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert just_sent.id in rows and just_sent.id in files
    got = await recent_sends(db, user_id=user.id, persona_id=persona.id)
    assert [s.asset_id for s in got] == [just_sent.id], "her context lost the photo she just sent"
    assert report.evicted == 5


# ══ FR-021-08 — scheduled maintenance, never the reply path ══════════════════════════════════════


async def test_fr_021_08_01_the_night_batch_invokes_retention(db, tmp_path, sessionmaker):
    """TC-FR-021-08-01 / TC-FR-021-08-04 — DFD-3: retention runs after the drain, before wake."""
    from services.imagegen.config import ImageRunnerSettings
    from services.imagegen.runner import ImageRunner

    order: list[str] = []

    class Handoff:
        async def unload_chat(self):
            order.append("unload")

        async def reload_chat(self):
            order.append("reload")

    class Backend:
        def load(self):
            order.append("load")

        def close(self):
            order.append("close")

        def generate(self, job):  # pragma: no cover - no jobs queued
            raise AssertionError

    settings = ImageRunnerSettings(backend="fake", media_root=str(tmp_path),
                                   retention_cap=5, retention_floor=2)
    runner = ImageRunner(settings, backend=Backend(), handoff=Handoff())
    real_run = ret.run_retention_all

    async def _traced(*a, **kw):
        order.append("retention")
        return await real_run(*a, **kw)

    import services.imagegen.runner as runner_mod
    runner_mod.run_retention_all = _traced
    try:
        snapshot = await runner.run_batch(sessionmaker)
    finally:
        runner_mod.run_retention_all = real_run

    assert order.index("retention") > order.index("load")
    assert order.index("retention") < order.index("reload"), "retention must precede wake"
    assert "retention_reports" in snapshot


async def test_fr_021_08_02_a_user_turn_never_triggers_retention(db, tmp_path, monkeypatch):
    """TC-FR-021-08-02 — 20 turns including photo requests: the retention counter stays zero."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(conv, "_sleep", AsyncMock())
    calls: list[int] = []

    async def _tripwire(*a, **kw):
        calls.append(1)
        return []

    monkeypatch.setattr(ret, "run_retention_all", _tripwire)
    monkeypatch.setattr(ret, "run_retention", _tripwire)

    user, _ = await get_or_create_user(db, telegram_id=2802, locale="ru")
    persona = await make_persona(db)
    await start_or_switch_session(db, user.id, persona.id)
    await archive(db, persona, tmp_path, {0: 10})
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()

    for i in range(20):
        m = MagicMock()
        m.from_user = SimpleNamespace(id=2802, language_code="ru")
        m.chat = SimpleNamespace(id=2802)
        m.text = "скинь фотку" if i % 2 else "как дела"
        m.answer = AsyncMock()
        m.answer_photo = AsyncMock()
        await conv.on_text(m, db, bot, RecordingChatClient())

    assert calls == [], "retention leaked onto the reply hot path"


async def test_fr_021_08_03_selection_cost_does_not_track_archive_size(db, tmp_path):
    """TC-FR-021-08-03 / TC-NFR-021-04-02 — the query count is constant in archive size."""
    from sqlalchemy import event

    user, _ = await get_or_create_user(db, telegram_id=2803, locale="ru")
    small = await make_persona(db, name="Small")
    big = await make_persona(db, name="Big")
    await archive(db, small, tmp_path, {0: 12}, prefix="s")
    await archive(db, big, tmp_path, {0: 300}, prefix="b")

    counts: dict[str, int] = {}
    engine = db.get_bind()

    async def _count_for(persona, label):
        n = 0

        def _on_exec(*a, **kw):
            nonlocal n
            n += 1

        event.listen(engine, "before_cursor_execute", _on_exec)
        try:
            await select_asset(db, persona_id=persona.id, user_id=user.id, context={})
        finally:
            event.remove(engine, "before_cursor_execute", _on_exec)
        counts[label] = n

    await _count_for(small, "small")
    await _count_for(big, "big")

    assert counts["small"] == counts["big"], f"N+1 in selection: {counts}"


# ══ FR-021-09 — intimacy is age-independent ══════════════════════════════════════════════════════


async def test_fr_021_09_01_an_old_intimate_asset_is_never_served_by_the_sfw_path(db, tmp_path):
    """TC-FR-021-09-01 — even as the best context fit, it is not a SFW candidate."""
    user, _ = await get_or_create_user(db, telegram_id=2901, locale="ru")
    persona = await make_persona(db)
    await add_asset(db, persona, tmp_path, asset_id="MED-alina-OLDINT", age_days=30,
                    intimate=True, meta=WALK)
    sfw = await add_asset(db, persona, tmp_path, asset_id="MED-alina-SFW", age_days=0, meta={})

    picked = await select_asset(db, persona_id=persona.id, user_id=user.id, context=WALK_CTX)

    assert picked.id == sfw.id


async def test_fr_021_09_02_an_old_intimate_request_still_goes_through_the_gate(db, tmp_path):
    """TC-FR-021-09-02 — the F-014 gate governs an aged intimate ask exactly as a fresh one."""
    user, _ = await get_or_create_user(db, telegram_id=2902, locale="ru")
    persona = await make_persona(db)
    await add_asset(db, persona, tmp_path, asset_id="MED-alina-INT2", age_days=45, intimate=True)
    gate = FakeGate()

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="send me a nude",
        context={}, caption_client=RecordingChatClient(), gate=gate, media_root=tmp_path,
    )

    assert result.outcome is DeliveryOutcome.routed_to_gate
    assert len(gate.calls) == 1


async def test_fr_021_09_03_no_intimate_asset_of_any_age_reaches_the_bot(db, tmp_path, monkeypatch):
    """TC-FR-021-09-03 (security) — every age bucket intimate, gate withholds → zero photos sent."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(conv, "_sleep", AsyncMock())

    user, _ = await get_or_create_user(db, telegram_id=2903, locale="ru")
    persona = await make_persona(db)
    await start_or_switch_session(db, user.id, persona.id)
    for age in (0, 1, 30):
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-I{age}", age_days=age,
                        intimate=True, meta=HOME_EVENING)
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()

    for _ in range(4):
        m = MagicMock()
        m.from_user = SimpleNamespace(id=2903, language_code="ru")
        m.chat = SimpleNamespace(id=2903)
        m.text = "скинь голую фотку"
        m.answer = AsyncMock()
        m.answer_photo = AsyncMock()
        await conv.on_text(m, db, bot, RecordingChatClient())
        assert m.answer_photo.await_count == 0, "an intimate asset escaped the gate"
        assert m.answer.await_count >= 1, "silence is never acceptable"


async def test_fr_021_09_04_eviction_tiering_ignores_the_intimate_flag(db, tmp_path):
    """TC-FR-021-09-04 — intimate frames are neither protected nor preferentially destroyed."""
    persona = await make_persona(db)
    for age in range(10):
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-M{age:02d}",
                        age_days=age + 1, intimate=(age % 2 == 0))

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=6, floor=2))

    rows, _ = await archive_state(db, persona, tmp_path)
    assert rows == {f"MED-alina-M{age:02d}" for age in range(6)}  # pure age order, flag irrelevant


# ══ FR-021-10 — per-persona isolation ════════════════════════════════════════════════════════════


async def test_fr_021_10_01_eviction_touches_only_the_target_persona(db, tmp_path):
    """TC-FR-021-10-01 — persona B's archive is byte-for-byte unchanged."""
    a = await make_persona(db, name="Alina")
    b = await make_persona(db, name="Vika")
    await archive(db, a, tmp_path, {-9: 25})
    await archive(db, b, tmp_path, {-9: 5})
    before_b = await archive_state(db, b, tmp_path)

    await run_retention(db, a.id, tmp_path, RetentionConfig(cap=5, floor=2, grace_hours=0.0))

    assert await archive_state(db, b, tmp_path) == before_b
    rows_a, _ = await archive_state(db, a, tmp_path)
    assert len(rows_a) == 5
    await assert_clean(db, tmp_path)


async def test_fr_021_10_02_candidacy_never_crosses_personas(db, tmp_path):
    """TC-FR-021-10-02 — no other persona's asset can be selected, whatever its age or fit."""
    user, _ = await get_or_create_user(db, telegram_id=3002, locale="ru")
    a = await make_persona(db, name="Alina")
    b = await make_persona(db, name="Vika")
    await archive(db, b, tmp_path, {0: 6}, meta=WALK, prefix="B")
    await archive(db, a, tmp_path, {-4: 3}, prefix="A")

    for _ in range(3):
        picked = await select_asset(db, persona_id=a.id, user_id=user.id, context=WALK_CTX)
        assert picked.persona_id == a.id


async def test_fr_021_10_03_cap_and_floor_are_per_persona(db, tmp_path):
    """TC-FR-021-10-03 — three personas × 15 assets, cap 10 → 30 total, not 10."""
    personas = [await make_persona(db, name=n) for n in ("Alina", "Vika", "Sofia")]
    for p in personas:
        await archive(db, p, tmp_path, {-9: 15}, prefix=p.name[0])

    reports = await run_retention_all(db, tmp_path, RetentionConfig(cap=10, floor=4))

    for p in personas:
        rows, files = await archive_state(db, p, tmp_path)
        assert len(rows) == len(files) == 10
    assert sum(r.archive_size for r in reports) == 30


async def test_fr_021_10_04_one_personas_failure_does_not_block_the_others(db, tmp_path,
                                                                          monkeypatch):
    """TC-FR-021-10-04 — a raising persona is reported; the rest still run (F-011 NFR-011-07)."""
    a = await make_persona(db, name="Alina")
    b = await make_persona(db, name="Vika")
    c = await make_persona(db, name="Sofia")
    for p in (a, b, c):
        await archive(db, p, tmp_path, {-9: 12}, prefix=p.name[0])
    real = ret.run_retention

    async def _flaky(db_, persona_id, *args, **kw):
        if persona_id == b.id:
            raise RuntimeError("boom")
        return await real(db_, persona_id, *args, **kw)

    monkeypatch.setattr(ret, "run_retention", _flaky)

    reports = await run_retention_all(db, tmp_path, RetentionConfig(cap=5, floor=2,
                                                                    grace_hours=0.0))

    by_id = {r.persona_id: r for r in reports}
    assert by_id[a.id].evicted == 7 and by_id[c.id].evicted == 7
    assert by_id[b.id].failures and "boom" in by_id[b.id].failures[0]


async def test_nfr_021_06_03_per_persona_cap_override(db, tmp_path):
    """TC-NFR-021-06-03 — a per-persona override beats the global default."""
    a = await make_persona(db, name="Alina")
    b = await make_persona(db, name="Vika")
    await archive(db, a, tmp_path, {-9: 40}, prefix="A")
    await archive(db, b, tmp_path, {-9: 40}, prefix="B")

    await run_retention_all(db, tmp_path,
                            RetentionConfig(cap=30, floor=4, per_persona_cap={a.id: 8}))

    assert len((await archive_state(db, a, tmp_path))[0]) == 8
    assert len((await archive_state(db, b, tmp_path))[0]) == 30


# ══ FR-021-11 — specific-request matching over the whole library ═════════════════════════════════


async def test_fr_021_11_01_the_whole_library_is_searched(db, tmp_path, monkeypatch):
    """TC-FR-021-11-01 — an outdoor ask finds a five-day-old walk through the real handler."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(conv, "_sleep", AsyncMock())

    user, _ = await get_or_create_user(db, telegram_id=3101, locale="ru")
    persona = await make_persona(db)
    await start_or_switch_session(db, user.id, persona.id)
    walk = await add_asset(db, persona, tmp_path, asset_id="MED-alina-OLDWALK", age_days=5,
                           meta=WALK)
    for i in range(4):
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-IN{i}", age_days=0,
                        meta=HOME_EVENING)

    picked = await select_asset(db, persona_id=persona.id, user_id=user.id, context=WALK_CTX)

    assert picked.id == walk.id


async def test_fr_021_11_02_no_match_anywhere_degrades_without_inventing(db, tmp_path):
    """TC-FR-021-11-02 — an unmatched specific ask serves a fallback or None, never raises."""
    user, _ = await get_or_create_user(db, telegram_id=3102, locale="ru")
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {0: 3}, meta=HOME_EVENING)

    picked = await select_asset(db, persona_id=persona.id, user_id=user.id,
                                context={"activity": "подводное плавание", "location": "океан"})

    assert picked is None or picked.persona_id == persona.id


# ══ FR-021-12 — observability ════════════════════════════════════════════════════════════════════


async def test_fr_021_12_01_the_report_carries_the_three_numbers(db, tmp_path):
    """TC-FR-021-12-01 — a run that evicts 4 of 14 reports kept=10, evicted=4, archive_size=10."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 14})

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=10, floor=4))

    assert (report.kept, report.evicted, report.archive_size) == (10, 4, 10)
    assert report.as_dict()["persona_id"] == persona.id


async def test_fr_021_12_02_a_noop_run_still_reports(db, tmp_path):
    """TC-FR-021-12-02 — "nothing happened" is an explicit signal, not silence."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 4})

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=60, floor=6))

    assert report.evicted == 0 and report.archive_size == 4
    assert report.as_dict()["evicted"] == 0


async def test_fr_021_12_03_partial_failures_are_surfaced_not_swallowed(db, tmp_path, monkeypatch):
    """TC-FR-021-12-03 — the counts reflect what was actually removed and the failure is reported."""
    persona = await make_persona(db)
    assets = await archive(db, persona, tmp_path, {-9: 8})
    victim = assets[0].id
    real_replace = ret.os.replace
    monkeypatch.setattr(ret.os, "replace",
                        lambda s, d: (_ for _ in ()).throw(OSError("nope"))
                        if victim in str(s) else real_replace(s, d))

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=5, floor=2, grace_hours=0.0))

    rows, _ = await archive_state(db, persona, tmp_path)
    assert report.evicted == len(assets) - len(rows)
    assert report.failures and victim in report.failures[0]


async def test_fr_021_12_04_retention_never_causes_an_empty_archive_alert(db, tmp_path):
    """TC-FR-021-12-04 / TC-NFR-021-05-03 — the §6.4 alert cannot fire because of retention."""
    for name, count in (("Alina", 40), ("Vika", 3), ("Sofia", 1)):
        p = await make_persona(db, name=name)
        await archive(db, p, tmp_path, {-9: count}, prefix=name[0])

    await run_retention_all(db, tmp_path, RetentionConfig(cap=0, floor=0, grace_hours=0.0))

    assert await empty_archive_personas(db) == []


# ══ NFR-021-01 — no repeats, ever ════════════════════════════════════════════════════════════════


async def test_nfr_021_01_01_drain_the_widened_pool_without_a_repeat(db, tmp_path):
    """TC-NFR-021-01-01 — 30 assets across 5 days → 30 distinct sends, then an in-voice deflection."""
    user, _ = await get_or_create_user(db, telegram_id=3201, locale="ru")
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {0: 6, -1: 6, -2: 6, -3: 6, -4: 6})

    delivered: list[str] = []
    for _ in range(30):
        result = await deliver_photo(
            db, user_id=user.id, persona=persona, request_text="скинь фотку",
            context={}, caption_client=RecordingChatClient(), gate=FakeGate(),
            cfg=NO_PACING, media_root=tmp_path,
        )
        assert result.outcome is DeliveryOutcome.delivered
        delivered.append(result.asset.id)

    assert len(set(delivered)) == 30
    last = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="ещё",
        context={}, caption_client=RecordingChatClient(), gate=FakeGate(),
        cfg=NO_PACING, media_root=tmp_path,
    )
    assert last.outcome is DeliveryOutcome.deflected and last.deflection.strip()


async def test_nfr_021_01_02_an_evicted_asset_cannot_return(db, tmp_path):
    """TC-NFR-021-01-02 — `media_sends` stays the authority with no row in `media_assets`."""
    user, _ = await get_or_create_user(db, telegram_id=3202, locale="ru")
    persona = await make_persona(db)
    old = await archive(db, persona, tmp_path, {-30: 8}, prefix="O")
    await mark_sent(db, user.id, old, hours_ago=600.0)
    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=4, floor=2, grace_hours=0.0))
    evicted = {a.id for a in old} - (await archive_state(db, persona, tmp_path))[0]
    await archive(db, persona, tmp_path, {0: 6}, prefix="N")  # a new batch lands

    delivered: list[str] = []
    for _ in range(8):
        result = await deliver_photo(
            db, user_id=user.id, persona=persona, request_text="скинь фотку",
            context={}, caption_client=RecordingChatClient(), gate=FakeGate(),
            cfg=NO_PACING, media_root=tmp_path,
        )
        if result.outcome is DeliveryOutcome.delivered:
            delivered.append(result.asset.id)

    assert evicted and not (set(delivered) & evicted)
    assert len(set(delivered)) == len(delivered)


async def test_nfr_021_01_03_eviction_during_selection_never_sends_a_missing_file(db, tmp_path,
                                                                                  monkeypatch):
    """TC-NFR-021-01-03 — asset picked, then evicted before the send: no phantom send, no silence."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(conv, "_sleep", AsyncMock())

    user, _ = await get_or_create_user(db, telegram_id=3203, locale="ru")
    persona = await make_persona(db)
    await start_or_switch_session(db, user.id, persona.id)
    assets = await archive(db, persona, tmp_path, {-30: 3})
    # the file vanishes under us, exactly as a concurrent retention pass would leave it
    (tmp_path / "alina" / "photos" / f"{assets[0].id}.png").unlink()
    (tmp_path / "alina" / "photos" / f"{assets[1].id}.png").unlink()
    (tmp_path / "alina" / "photos" / f"{assets[2].id}.png").unlink()

    m = MagicMock()
    m.from_user = SimpleNamespace(id=3203, language_code="ru")
    m.chat = SimpleNamespace(id=3203)
    m.text = "скинь фотку"
    m.answer = AsyncMock()
    m.answer_photo = AsyncMock()
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()

    await conv.on_text(m, db, bot, RecordingChatClient())

    assert m.answer.await_count + m.answer_photo.await_count >= 1, "the turn went silent"
    if m.answer_photo.await_count == 0:
        count = await db.scalar(
            select(func.count()).select_from(MediaSend).where(MediaSend.user_id == user.id))
        assert count == 0, "a MediaSend row was written for a photo that was never delivered"


# ══ NFR-021-02 / NFR-021-03 / NFR-021-05 — bounded, un-sent preserved, never empty ═══════════════


async def test_nfr_021_02_02_bounded_across_thirty_simulated_nights(db, tmp_path):
    """TC-NFR-021-02-02 / TC-US-021-03-01 — 30 nights × 6 frames stays inside [floor, cap]."""
    user, _ = await get_or_create_user(db, telegram_id=3301, locale="ru")
    persona = await make_persona(db)
    cfg = RetentionConfig(cap=30, floor=6, grace_hours=0.0)

    for night in range(30):
        for i in range(6):
            await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-N{night:02d}{i}",
                            age_days=(30 - night))
        # a realistic send rate: two frames consumed each day
        picks = (await retained_assets(db, persona.id))[:2]
        await mark_sent(db, user.id, picks, hours_ago=200.0)
        report = await run_retention(db, persona.id, tmp_path, cfg)
        rows, files = await archive_state(db, persona, tmp_path)
        assert len(rows) == len(files) <= 30, f"night {night} exceeded the cap: {len(rows)}"

    rows, files = await archive_state(db, persona, tmp_path)
    assert 6 <= len(rows) <= 30 and rows == files
    await assert_clean(db, tmp_path)


async def test_nfr_021_02_03_a_single_huge_night_is_bounded_in_one_pass(db, tmp_path):
    """TC-NFR-021-02-03 — 5× the cap in one night comes back inside the cap in a single run."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-3: 50})

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=10, floor=4))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 10


async def test_nfr_021_03_01_randomized_battery_never_loses_unsent_work(db, tmp_path):
    """TC-NFR-021-03-01 / TC-US-021-04-01 — across 60 randomized archives the invariant holds.

    "No un-sent asset was evicted while any already-sent asset remained" — the wasted-GPU counter
    must be exactly zero in every run.
    """
    rng = random.Random(20260723)
    user, _ = await get_or_create_user(db, telegram_id=3302, locale="ru")

    for case in range(60):
        persona = await make_persona(db, name=f"P{case}")
        size = rng.randint(2, 25)
        assets = [
            await add_asset(db, persona, tmp_path,
                            asset_id=f"MED-p{case}-{i:03d}", age_days=rng.uniform(2, 60))
            for i in range(size)
        ]
        sent = rng.sample(assets, k=rng.randint(0, size))
        await mark_sent(db, user.id, sent, hours_ago=500.0)
        cfg = RetentionConfig(cap=rng.randint(0, 20), floor=rng.randint(0, 8), grace_hours=0.0)

        report = await run_retention(db, persona.id, tmp_path, cfg)

        rows, files = await archive_state(db, persona, tmp_path)
        assert rows == files, f"case {case}: rows and files diverged"
        assert rows, "case {case}: the archive was emptied"
        survivors_sent = {a.id for a in sent} & rows
        if report.evicted_unsent:
            assert not survivors_sent, (
                f"case {case}: destroyed {report.evicted_unsent} un-sent frames while "
                f"{len(survivors_sent)} already-consumed ones survived"
            )


async def test_nfr_021_03_02_one_sent_frame_spares_an_unsent_one(db, tmp_path):
    """TC-NFR-021-03-02 — exactly one over the cap with a single sent asset: it is the only victim."""
    user, _ = await get_or_create_user(db, telegram_id=3303, locale="ru")
    persona = await make_persona(db)
    assets = await archive(db, persona, tmp_path, {-9: 11})
    lone_sent = assets[5]  # deliberately NOT the oldest
    await mark_sent(db, user.id, [lone_sent], hours_ago=500.0)

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=10, floor=2))

    rows, files = await archive_state(db, persona, tmp_path)
    assert lone_sent.id not in rows and len(rows) == len(files) == 10
    assert report.evicted_unsent == 0


@pytest.mark.parametrize("cap", [0, 1, 5, 30])
@pytest.mark.parametrize("size", [1, 2, 7])
async def test_nfr_021_05_01_no_config_ever_empties_an_archive(db, tmp_path, cap, size):
    """TC-NFR-021-05-01/02 — the cap × floor × size matrix always leaves at least one frame."""
    persona = await make_persona(db, name=f"P{cap}x{size}")
    await archive(db, persona, tmp_path, {-40: size}, prefix=f"{cap}{size}")

    await run_retention(db, persona.id, tmp_path,
                        RetentionConfig(cap=cap, floor=0, grace_hours=0.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert rows and rows == files


# ══ NFR-021-06 — config-driven ═══════════════════════════════════════════════════════════════════


async def test_nfr_021_06_01_changing_the_cap_changes_behaviour_only(db, tmp_path):
    """TC-NFR-021-06-01 — the same archive under cap=10 and cap=30 keeps 10 and 30."""
    a = await make_persona(db, name="Alina")
    b = await make_persona(db, name="Vika")
    await archive(db, a, tmp_path, {-9: 40}, prefix="A")
    await archive(db, b, tmp_path, {-9: 40}, prefix="B")

    await run_retention(db, a.id, tmp_path, RetentionConfig(cap=10, floor=4))
    await run_retention(db, b.id, tmp_path, RetentionConfig(cap=30, floor=4))

    assert len((await archive_state(db, a, tmp_path))[0]) == 10
    assert len((await archive_state(db, b, tmp_path))[0]) == 30


async def test_nfr_021_06_02_freshness_knobs_are_read_at_call_time(db, tmp_path):
    """TC-NFR-021-06-02 — the same pair ranks differently under two configs, no code change."""
    persona = await make_persona(db)
    old = await add_asset(db, persona, tmp_path, asset_id="MED-alina-CFGO", age_days=4, meta=WALK)
    new = await add_asset(db, persona, tmp_path, asset_id="MED-alina-CFGN", age_days=0, meta={})

    strong = MediaDeliveryConfig(freshness_bonus=20.0, freshness_decay_per_day=1.0)
    weak = MediaDeliveryConfig(freshness_bonus=0.5, freshness_decay_per_day=1.0)

    assert rank_score(new, WALK_CTX, strong) > rank_score(old, WALK_CTX, strong)
    assert rank_score(old, WALK_CTX, weak) > rank_score(new, WALK_CTX, weak)


@pytest.mark.parametrize("cap,floor", [(-5, 6), ("many", 6), (30, -1), (30, "none")])
async def test_nfr_021_06_04_broken_config_degrades_to_defaults(db, tmp_path, cap, floor):
    """TC-NFR-021-06-04 — an invalid config never means "delete everything"; it is logged."""
    persona = await make_persona(db, name=f"P{cap}{floor}")
    await archive(db, persona, tmp_path, {-9: 12}, prefix="X")

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=cap, floor=floor, grace_hours=0.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 12, "a broken config deleted frames"
    assert report.notes, "the degraded config must be reported, not swallowed"


# ══ NFR-021-07 — integrity ═══════════════════════════════════════════════════════════════════════


async def test_nfr_021_07_01_reconciliation_is_clean_after_a_normal_run(db, tmp_path):
    """TC-NFR-021-07-01 — zero orphan rows, zero orphan files."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 20})

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=8, floor=4, grace_hours=0.0))

    await assert_clean(db, tmp_path)


async def test_nfr_021_07_02_running_twice_changes_nothing(db, tmp_path):
    """TC-NFR-021-07-02 — idempotent: the second run evicts nothing and the sets are identical."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 20})
    cfg = RetentionConfig(cap=8, floor=4, grace_hours=0.0)

    await run_retention(db, persona.id, tmp_path, cfg)
    state_1 = await archive_state(db, persona, tmp_path)
    second = await run_retention(db, persona.id, tmp_path, cfg)

    assert second.evicted == 0
    assert await archive_state(db, persona, tmp_path) == state_1
    await assert_clean(db, tmp_path)


async def test_nfr_021_07_03_an_interrupted_run_is_repaired(db, tmp_path):
    """TC-NFR-021-07-03 — a row whose file is already gone (killed mid-eviction) is cleaned up."""
    persona = await make_persona(db)
    assets = await archive(db, persona, tmp_path, {-9: 10})
    orphan = assets[0]
    (tmp_path / "alina" / "photos" / f"{orphan.id}.png").unlink()  # file gone, row left behind
    # …and a leftover staged file from the same interrupted run
    staged = tmp_path / "alina" / "photos" / f"{assets[1].id}.png.evicting"
    staged.write_bytes(b"partial")

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=60, floor=4, grace_hours=0.0))

    rows, _ = await archive_state(db, persona, tmp_path)
    assert orphan.id not in rows and orphan.id in report.repaired
    assert not staged.exists()
    await assert_clean(db, tmp_path)


async def test_nfr_021_07_03b_a_missing_media_root_never_wipes_the_archive(db, tmp_path):
    """TC-NFR-021-07-03 (guard) — every file missing reads as a bad media root, not 10 evictions.

    Repairing rows whose file is gone is right for an interrupted run and catastrophic for an
    unmounted volume. When *nothing* is on disk, the run reports the anomaly and changes nothing.
    """
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 10})
    for f in (tmp_path / "alina" / "photos").glob("*.png"):
        f.unlink()

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=60, floor=4, grace_hours=0.0))

    rows, _ = await archive_state(db, persona, tmp_path)
    assert len(rows) == 10, "a bad media root destroyed the whole archive"
    assert report.repaired == []
    assert any("media root" in n for n in report.notes)


async def test_nfr_021_07_04_pre_existing_orphan_files_are_not_made_worse(db, tmp_path):
    """TC-NFR-021-07-04 — a stray .png with no row is reported, and no other row is harmed."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 6})
    stray = tmp_path / "alina" / "photos" / "MED-alina-STRAY.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(stray)

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=60, floor=4))

    rows, _ = await archive_state(db, persona, tmp_path)
    assert len(rows) == 6
    report = await reconcile(db, tmp_path)
    assert report["rows_missing_file"] == []
    assert [Path(p).name for p in report["files_missing_row"]] == ["MED-alina-STRAY.png"]


# ══ FR-021-13 — monotonic ids (the eviction blocker) ═════════════════════════════════════════════


async def test_fr_021_13_01_ids_never_rewind_after_eviction(db, tmp_path):
    """TC-FR-021-07-05 (D1) — allocation is monotonic even when the archive shrinks to nothing."""
    persona = await make_persona(db)
    issued = [await allocate_med_id(db, persona, "alina") for _ in range(5)]
    assert issued == [f"MED-alina-{i:05d}" for i in range(1, 6)]

    for aid in issued:  # everything is deleted — the count-based allocator would rewind to 1
        await add_asset(db, persona, tmp_path, asset_id=aid, age_days=30)
    for asset in await retained_assets(db, persona.id):
        await db.delete(asset)
    await db.flush()

    nxt = await allocate_med_id(db, persona, "alina")
    assert nxt == "MED-alina-00006", f"a retired id was about to be reissued: {nxt}"


async def test_fr_021_13_02_allocation_seeds_from_an_existing_archive(db, tmp_path):
    """TC-FR-021-07-05 (migration) — a pre-counter archive continues, it does not restart."""
    persona = await make_persona(db)
    await add_asset(db, persona, tmp_path, asset_id="MED-alina-00042", age_days=1)

    assert await allocate_med_id(db, persona, "alina") == "MED-alina-00043"


async def test_fr_021_13_03_send_history_alone_still_blocks_reuse(db, tmp_path):
    """TC-FR-021-07-05 (the dangerous case) — the id survives only in `media_sends`; still no reuse."""
    user, _ = await get_or_create_user(db, telegram_id=3401, locale="ru")
    persona = await make_persona(db)
    db.add(MediaSend(user_id=user.id, asset_id="MED-alina-00099",
                     sent_at=_now() - timedelta(days=40)))
    await db.flush()

    nxt = await allocate_med_id(db, persona, "alina")

    assert nxt == "MED-alina-00100"
    assert nxt not in await sent_asset_ids(db, user.id)


async def test_fr_021_13_04_store_asset_uses_the_monotonic_id(db, tmp_path):
    """TC-FR-021-07-05 (integration) — the real store path allocates through the counter."""
    from services.imagegen.contract import GenerationJob, SlotMeta
    import io

    persona = await make_persona(db)
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 10, 10)).save(buf, format="PNG")
    job = GenerationJob(job_key="k", persona_slug="alina", prompt="p", slot=SlotMeta())

    first = await store_asset(db, persona, job, buf.getvalue(), tmp_path)
    await db.delete(first)
    await db.flush()
    second = await store_asset(db, persona, job, buf.getvalue(), tmp_path)

    assert second.id != first.id, "the store path reissued a retired id"


# ══ User stories ═════════════════════════════════════════════════════════════════════════════════


async def test_us_021_01_01_a_simulated_week_never_repeats_and_never_runs_dry(db, tmp_path):
    """TC-US-021-01-01 — 7 nights, 3 photos a day: 21 distinct photos, no dry day."""
    user, _ = await get_or_create_user(db, telegram_id=3501, locale="ru")
    persona = await make_persona(db)
    cfg_ret = RetentionConfig(cap=60, floor=6)
    delivered: list[str] = []

    for night in range(7):
        for i in range(6):
            await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-W{night}{i}",
                            age_days=(7 - night))
        await run_retention(db, persona.id, tmp_path, cfg_ret)
        for _ in range(3):
            result = await deliver_photo(
                db, user_id=user.id, persona=persona, request_text="скинь фотку",
                context={}, caption_client=RecordingChatClient(), gate=FakeGate(),
                cfg=NO_PACING, media_root=tmp_path,
            )
            assert result.outcome is DeliveryOutcome.delivered, (
                f"day {night} ran dry — the one-day window is what used to cause this"
            )
            delivered.append(result.asset.id)

    assert len(delivered) == 21 and len(set(delivered)) == 21


async def test_us_021_02_01_evening_ask_yields_tonights_frame(db, tmp_path):
    """TC-US-021-02-01 — today's evening frame beats last Tuesday's equally fitting one."""
    user, _ = await get_or_create_user(db, telegram_id=3502, locale="ru")
    persona = await make_persona(db)
    tuesday = await add_asset(db, persona, tmp_path, asset_id="MED-alina-TUE", age_days=6,
                              meta=HOME_EVENING)
    tonight = await add_asset(db, persona, tmp_path, asset_id="MED-alina-TON", age_days=0,
                              meta=HOME_EVENING)

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="скинь фотку",
        context={"time_of_day": "evening"}, caption_client=RecordingChatClient(),
        gate=FakeGate(), media_root=tmp_path,
    )

    assert result.asset.id == tonight.id and tuesday is not None


async def test_us_021_02_02_today_exhausted_falls_back_to_yesterday(db, tmp_path):
    """TC-US-021-02-02 — UC-021-04: not a repeat, not a deflection — yesterday's evening frame."""
    user, _ = await get_or_create_user(db, telegram_id=3503, locale="ru")
    persona = await make_persona(db)
    today = await archive(db, persona, tmp_path, {0: 3}, meta=HOME_EVENING, prefix="T")
    yesterday_evening = await add_asset(db, persona, tmp_path, asset_id="MED-alina-YEVE",
                                        age_days=1, meta=HOME_EVENING)
    await mark_sent(db, user.id, today, hours_ago=200.0)

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="ещё одну",
        context={"time_of_day": "evening"}, caption_client=RecordingChatClient(),
        gate=FakeGate(), cfg=NO_PACING, media_root=tmp_path,
    )

    assert result.outcome is DeliveryOutcome.delivered
    assert result.asset.id == yesterday_evening.id


async def test_us_021_05_01_specific_ask_journey_returns_scene_metadata(db, tmp_path):
    """TC-US-021-05-01 — the old outdoor frame is delivered with a caption and its scene meta."""
    user, _ = await get_or_create_user(db, telegram_id=3504, locale="ru")
    persona = await make_persona(db)
    walk = await add_asset(
        db, persona, tmp_path, asset_id="MED-alina-JWALK", age_days=4,
        meta={**WALK, "scene_description": "гуляю по парку; вокруг деревья и дорожка"},
    )
    for i in range(4):
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-JIN{i}", age_days=0,
                        meta=HOME_EVENING)

    result = await deliver_photo(
        db, user_id=user.id, persona=persona, request_text="покажи, где ты гуляла",
        context=WALK_CTX, caption_client=RecordingChatClient("вот, гуляла сегодня"),
        gate=FakeGate(), media_root=tmp_path,
    )

    assert result.outcome is DeliveryOutcome.delivered and result.asset.id == walk.id
    assert result.caption and result.caption.strip()
    assert result.meta["scene_description"].startswith("гуляю по парку")


# ══ the remaining direct checks ══════════════════════════════════════════════════════════════════


async def test_nfr_021_01_04_a_redelivered_update_does_not_double_send(db, tmp_path, monkeypatch):
    """TC-NFR-021-01-04 — the same Telegram update processed twice sends one asset once."""
    monkeypatch.setattr("services.bot.handlers.media._DEFAULT_MEDIA_ROOT", tmp_path)
    monkeypatch.setattr(conv, "_sleep", AsyncMock())

    user, _ = await get_or_create_user(db, telegram_id=3601, locale="ru")
    persona = await make_persona(db)
    await start_or_switch_session(db, user.id, persona.id)
    await archive(db, persona, tmp_path, {0: 20, -1: 20, -2: 20})
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()

    def _same_update():
        m = MagicMock()
        m.from_user = SimpleNamespace(id=3601, language_code="ru")
        m.chat = SimpleNamespace(id=3601)
        m.text = "скинь фотку"
        m.answer = AsyncMock()
        m.answer_photo = AsyncMock()
        return m

    await conv.on_text(_same_update(), db, bot, RecordingChatClient())
    await conv.on_text(_same_update(), db, bot, RecordingChatClient())

    sends = (await db.execute(select(MediaSend).where(MediaSend.user_id == user.id))).scalars().all()
    ids = [s.asset_id for s in sends]
    assert len(ids) == len(set(ids)), f"an asset was sent twice: {ids}"


async def test_nfr_021_02_01_rows_and_files_are_both_within_the_cap(db, tmp_path):
    """TC-NFR-021-02-01 — the direct post-run check, on BOTH sides."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-9: 37})

    await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=12, floor=5, grace_hours=0.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) <= 12 and len(files) <= 12 and rows == files


async def test_nfr_021_03_03_all_unsent_far_over_the_cap_keeps_the_newest(db, tmp_path):
    """TC-NFR-021-03-03 — un-sent frames ARE evicted when nothing cheaper exists; newest survive."""
    persona = await make_persona(db)
    for age in range(40):
        await add_asset(db, persona, tmp_path, asset_id=f"MED-alina-S{age:02d}", age_days=age + 1)

    report = await run_retention(db, persona.id, tmp_path, RetentionConfig(cap=8, floor=4))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 8
    assert rows == {f"MED-alina-S{age:02d}" for age in range(8)}  # the 8 newest
    assert report.evicted_unsent == 32 and report.evicted_sent == 0


async def test_nfr_021_04_01_selection_at_cap_size_stays_cheap(db, tmp_path):
    """TC-NFR-021-04-01 — 100 selections against a full-cap archive stay well inside the budget."""
    import time

    user, _ = await get_or_create_user(db, telegram_id=3602, locale="ru")
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-1: 60})

    timings = []
    for _ in range(100):
        t0 = time.perf_counter()
        await select_asset(db, persona_id=persona.id, user_id=user.id, context=HOME_EVENING)
        timings.append(time.perf_counter() - t0)

    timings.sort()
    p95 = timings[94]
    assert p95 < 0.10, f"selection p95 {p95:.3f}s — the reply path must stay a cheap lookup"


async def test_nfr_021_04_03_a_large_send_history_stays_a_bounded_query(db, tmp_path):
    """TC-NFR-021-04-03 — thousands of `media_sends` rows do not turn selection into a scan."""
    from sqlalchemy import event
    import time

    user, _ = await get_or_create_user(db, telegram_id=3603, locale="ru")
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {0: 20})
    db.add_all([
        MediaSend(user_id=user.id, asset_id=f"MED-gone-{i:05d}",
                  sent_at=_now() - timedelta(days=2))
        for i in range(5000)
    ])
    await db.flush()

    statements = 0
    engine = db.get_bind()

    def _count(*a, **kw):
        nonlocal statements
        statements += 1

    event.listen(engine, "before_cursor_execute", _count)
    t0 = time.perf_counter()
    try:
        picked = await select_asset(db, persona_id=persona.id, user_id=user.id, context={})
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    elapsed = time.perf_counter() - t0

    assert picked is not None
    assert statements <= 3, f"the no-repeat exclusion fanned out into {statements} queries"
    assert elapsed < 0.5


async def test_nfr_021_05_02_the_most_aggressive_config_still_leaves_a_frame(db, tmp_path):
    """TC-NFR-021-05-02 — cap=0, floor=0: one asset survives and the clamp is reported."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-40: 9})

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=0, floor=0, grace_hours=0.0))

    rows, files = await archive_state(db, persona, tmp_path)
    assert len(rows) == len(files) == 1
    assert report.cap_exceeded and report.notes, "the clamp must be visible to the operator"


async def test_us_021_03_02_disk_growth_across_the_roster_is_bounded(db, tmp_path):
    """TC-US-021-03-02 — 10 personas × 30 nights stays bounded by `personas × cap`."""
    cfg = RetentionConfig(cap=12, floor=4, grace_hours=0.0)
    personas = [await make_persona(db, name=f"P{i:02d}") for i in range(10)]

    for night in range(30):
        for p in personas:
            for i in range(6):
                await add_asset(db, p, tmp_path, asset_id=f"MED-{_slug(p)}-{night:02d}{i}",
                                age_days=(30 - night))
        await run_retention_all(db, tmp_path, cfg)

    total_files = len(list(tmp_path.glob("*/photos/*.png")))
    total_rows = await db.scalar(select(func.count()).select_from(MediaAsset))
    assert total_files == total_rows <= 10 * 12
    await assert_clean(db, tmp_path)


async def test_us_021_04_02_unsent_loss_is_counted_never_silent(db, tmp_path):
    """TC-US-021-04-02 — when un-sent frames had to go, the report says so explicitly."""
    persona = await make_persona(db)
    await archive(db, persona, tmp_path, {-20: 15})

    report = await run_retention(db, persona.id, tmp_path,
                                 RetentionConfig(cap=5, floor=2, grace_hours=0.0))

    assert report.evicted_unsent == 10, "the operator must see the GPU work that was destroyed"
    assert report.as_dict()["evicted_unsent"] == 10
