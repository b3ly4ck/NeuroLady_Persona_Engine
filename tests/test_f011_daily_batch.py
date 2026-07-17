"""F-011 Daily SFW Photo Batch tests — one runnable test per declared TC.

Maps 1:1 to `developer files/tests/F-011-daily-sfw-photo-batch.md`. The planner orchestrates: it
reads F-006 plans, derives slots, and enqueues F-008 jobs. Everything runs for real against the
shared in-memory DB with a fake F-010 PromptAuthor and, for end-to-end planner→runner cases, the
deterministic FakeBackend (services/imagegen/testing.py) + a tmp media root. GPU/throughput/manual
TCs are explicit skips (same discipline as the F-008 suite).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from services.bot.models import MediaAsset, MediaJob, MediaJobStatus, Persona, PersonaStatus
from services.bot.personas_seed import persona_slug
from services.imagegen import queue_ops, store
from services.imagegen.batch_planner import (
    AuthoredShot,
    BatchPlanConfig,
    BatchPlanner,
    DefaultPromptAuthor,
    DefaultReferenceProvider,
    SlotContext,
    derive_slots,
    job_key_for,
)
from services.imagegen.config import ImageRunnerSettings
from services.imagegen.contract import GenerationJob, SlotMeta
from services.imagegen.runner import ImageRunner, in_media_window
from services.imagegen.testing import FakeBackend, RecordingHandoff

IMAGEGEN_DIR = Path(__file__).resolve().parent.parent / "services" / "imagegen"

TARGET_DATE = "2026-07-18"
FULL_PLAN = (
    "07:00 morning run in the park. 09:00 coffee at the cafe. 13:00 work at the office. "
    "19:00 dinner at a restaurant. 22:00 winding down at home."
)  # 5 slots: morning, morning, afternoon, evening, night


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────


def make_settings(tmp_path: Path, **overrides) -> ImageRunnerSettings:
    base = dict(
        backend="fake",
        media_root=str(tmp_path / "media"),
        backoff_base_s=0.0,
        stale_running_s=0.0,
        max_attempts=3,
        window_start_hour=1,
        window_end_hour=8,
    )
    base.update(overrides)
    return ImageRunnerSettings(**base)


async def make_persona(db, name: str = "Testgirl", tz: str = "UTC", **kw) -> Persona:
    p = Persona(name=name, timezone=tz, **kw)
    db.add(p)
    await db.flush()
    return p


async def make_plan(db, persona: Persona, plan_text: str = FULL_PLAN, date_key: str = TARGET_DATE):
    from services.bot.domain.life_engine_store import store_plan

    return await store_plan(db, persona.id, date_key, plan_text, "plan_day_v2")


def night(hour: int = 3) -> datetime:
    return datetime(2026, 7, 17, hour, 0, tzinfo=timezone.utc)


class FakeAuthor:
    """Fake F-010 author: records calls; can be scripted to raise for a given (slot_idx, shot)."""

    def __init__(self, fail_on: tuple[int, int] | None = None) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.fail_on = fail_on

    def author(self, persona: Persona, slot: SlotContext, shot_index: int) -> AuthoredShot:
        self.calls.append((persona.name, slot.idx, shot_index))
        if self.fail_on == (slot.idx, shot_index):
            raise RuntimeError("scripted author failure")
        return AuthoredShot(
            prompt=f"prompt::{persona.name}::{slot.time_of_day}::{shot_index}",
            negative="neg",
            slot=SlotMeta(pose=f"angle-{shot_index}", background=slot.location,
                          location=slot.location, activity=slot.activity,
                          time_of_day=slot.time_of_day),
        )


class FixedRefProvider:
    def __init__(self, refs: list[str]) -> None:
        self.refs = refs

    def references_for(self, persona: Persona) -> list[str]:
        return list(self.refs)


class FailRefProvider:
    """Raises for one persona (by slug) — triggers a whole-persona planning failure (NFR-011-07)."""

    def __init__(self, fail_slug: str) -> None:
        self.fail_slug = fail_slug

    def references_for(self, persona: Persona) -> list[str]:
        if persona_slug(persona.name) == self.fail_slug:
            raise RuntimeError("scripted reference failure")
        return []


class CrashOnSecondBackend(FakeBackend):
    """First job fine, second crashes the whole pass (simulates a mid-batch process crash)."""

    def generate(self, job: GenerationJob) -> bytes:
        if len(self.generate_calls) >= 1:
            self.generate_calls.append(job)
            raise RuntimeError("simulated process crash")
        return super().generate(job)


async def load_jobs(db) -> list[GenerationJob]:
    rows = (await db.execute(select(MediaJob))).scalars().all()
    return [GenerationJob.from_json(r.payload_json) for r in rows]


# ═══ FR-011-01 — nightly batch runs only in the media window ════════════════════════════════════


async def test_fr_011_01_01_batch_runs_in_night_window(db):
    p = await make_persona(db)
    planner = BatchPlanner(settings=make_settings(Path("/tmp")))
    assert planner.should_run([p], now=night(3)) is True  # 03:00 UTC — her sleep window


async def test_fr_011_01_02_batch_does_not_run_in_day_window(db):
    p = await make_persona(db)
    planner = BatchPlanner(settings=make_settings(Path("/tmp")))
    assert planner.should_run([p], now=night(15)) is False  # 15:00 UTC — serving hours


# ═══ FR-011-02 — reads tomorrow's plan → day's slots ════════════════════════════════════════════


async def test_fr_011_02_01_derives_days_slots_from_plan(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p)
    await db.commit()
    author = FakeAuthor()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), make_settings(tmp_path),
                           author=author, references=FixedRefProvider([]))
    metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert metrics.per_persona[0].slots_planned == 5  # five HH:MM slots derived
    tods = {c.slot.time_of_day for c in await load_jobs(db)}
    assert tods == {"morning", "afternoon", "evening", "night"}


async def test_fr_011_02_02_few_slots_only_those_covered(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="08:00 gym. 20:00 home.")
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert metrics.per_persona[0].slots_planned == 2  # only the two present slots
    assert metrics.jobs_enqueued == 4                 # 2 slots × 2 shots


# ═══ FR-011-03 — configurable SFW shot set per slot ═════════════════════════════════════════════


async def test_fr_011_03_01_six_shots_per_slot(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 coffee at the cafe.")
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=6), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert metrics.jobs_enqueued == 6  # one slot × 6 angles


async def test_fr_011_03_02_total_is_slots_times_n(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p)  # 5 slots
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=5), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert metrics.jobs_enqueued == 25  # 5 slots × 5 shots
    assert await db.scalar(select(func.count()).select_from(MediaJob)) == 25


async def test_fr_011_03_03_single_shot_per_slot(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p)  # 5 slots
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert metrics.jobs_enqueued == 5  # exactly one per slot


# ═══ FR-011-04 — dispatches via F-010 → F-008 with F-009 ════════════════════════════════════════


async def test_fr_011_04_01_job_carries_f010_prompt_and_f009_ref(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 coffee at the cafe.")
    await db.commit()
    refs = ["media/testgirl/reference/face.png"]
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider(refs))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    jobs = await load_jobs(db)
    assert len(jobs) == 1
    assert jobs[0].prompt.startswith("prompt::Testgirl::morning")  # F-010 authored the text
    assert jobs[0].references == refs                              # F-009 refs forwarded to F-008
    assert jobs[0].job_key == job_key_for("testgirl", TARGET_DATE, 0, 0)


def test_fr_011_04_02_planner_does_not_render_itself():
    src = (IMAGEGEN_DIR / "batch_planner.py").read_text()
    for banned in ("import torch", "from torch", "diffusers", "backends", "ComfyUIBackend",
                   "def generate(", ".generate("):
        assert banned not in src, f"planner leaks rendering: {banned}"


# ═══ FR-011-05 — assets dated and slot-tagged ═══════════════════════════════════════════════════


async def test_fr_011_05_01_stored_asset_dated_and_slot_tagged(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="07:00 a walk in the park.")
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    runner = ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff())
    await runner.run_batch(sessionmaker, now=night(3))
    asset = (await db.execute(select(MediaAsset))).scalar_one()
    meta = store.parse_meta(asset)
    assert meta["time_of_day"] == "morning" and meta["location"] == "outdoors"
    assert asset.created_at is not None  # dated via created_at (NFR-011-01)


async def test_fr_011_05_02_meta_json_tags_selectable(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="13:00 work at the office.")
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    job = (await load_jobs(db))[0]
    meta = job.slot
    assert (meta.time_of_day, meta.location) == ("afternoon", "office")
    assert {"pose", "background", "location", "activity", "time_of_day"} <= \
        set(vars(meta).keys())


# ═══ FR-011-06 — idempotent and resumable ═══════════════════════════════════════════════════════


async def test_fr_011_06_01_completed_slot_rerun_skipped(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p)
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    first = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    second = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert first.jobs_enqueued == 10 and second.jobs_enqueued == 0  # nothing re-created
    assert second.jobs_existing == 10
    assert await db.scalar(select(func.count()).select_from(MediaJob)) == 10  # no duplicates


async def test_fr_011_06_02_mid_run_crash_resumes(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="08:00 gym. 13:00 office. 20:00 home.")
    await db.commit()
    settings = make_settings(tmp_path)
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), settings,
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    with pytest.raises(RuntimeError):
        await ImageRunner(settings, CrashOnSecondBackend(), RecordingHandoff()).run_batch(
            sessionmaker, now=night(3))
    # resume: the stuck job requeues, the rest finish, done ones are untouched
    await ImageRunner(settings, FakeBackend(), RecordingHandoff()).run_batch(
        sessionmaker, now=night(3))
    statuses = [r.status for r in (await db.execute(select(MediaJob))).scalars().all()]
    assert statuses.count(MediaJobStatus.done) == 3
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 3


async def test_fr_011_06_03_idempotency_key_per_slot_shot(sessionmaker, db, tmp_path):
    assert job_key_for("alina", "2026-07-18", 2, 4) == "daily-alina-2026-07-18-2-4"
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=3), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)  # re-run
    keys = {r.job_key for r in (await db.execute(select(MediaJob))).scalars().all()}
    assert keys == {job_key_for("testgirl", TARGET_DATE, 0, i) for i in range(3)}


# ═══ FR-011-07 — graceful degrade on single-shot failure ════════════════════════════════════════


async def test_fr_011_07_01_one_shot_failure_rest_complete(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    # the author raises for shot index 1 only — the other shots must still be planned
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=4), make_settings(tmp_path),
                           author=FakeAuthor(fail_on=(0, 1)), references=FixedRefProvider([]))
    metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert metrics.shots_failed == 1
    assert metrics.jobs_enqueued == 3  # 4 asked, 1 failed, 3 enqueued
    assert not metrics.per_persona[0].failed


async def test_fr_011_07_02_shot_failure_logged_not_fatal(sessionmaker, db, tmp_path, caplog):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), make_settings(tmp_path),
                           author=FakeAuthor(fail_on=(0, 0)), references=FixedRefProvider([]))
    with caplog.at_level("WARNING"):
        metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert "plan shot failed" in caplog.text          # logged, not raised
    assert metrics.jobs_enqueued == 1 and metrics.shots_failed == 1


# ═══ FR-011-08 — completes before day window, no hot-path gen ════════════════════════════════════


async def test_fr_011_08_01_morning_archive_ready_no_hotpath(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="07:00 run. 09:00 cafe.")
    await db.commit()
    settings = make_settings(tmp_path)
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), settings,
                           author=FakeAuthor(), references=FixedRefProvider([]))
    result = await planner.run_nightly(
        sessionmaker, ImageRunner(settings, FakeBackend(), RecordingHandoff()),
        now=night(3), target_date=TARGET_DATE)
    assert result["ran"] is True
    # by "morning" the archive is fully rendered — nothing left pending (no hot-path generation)
    assert await queue_ops.pending_count(db) == 0
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 4


def test_fr_011_08_02_batch_fits_nightly_window():
    pytest.skip("TC-FR-011-08-02: GPU throughput benchmark — measured out-of-band (F-008 report)")


# ═══ FR-011-09 — configurable per-persona shot budget ═══════════════════════════════════════════


async def test_fr_011_09_01_per_persona_budget_honored(sessionmaker, db, tmp_path):
    a = await make_persona(db, "Alpha")
    b = await make_persona(db, "Beta")
    await make_plan(db, a, plan_text="09:00 cafe.")
    await make_plan(db, b, plan_text="09:00 cafe.")
    await db.commit()
    cfg = BatchPlanConfig(shots_per_slot=6, per_persona={"alpha": {"shots_per_slot": 3}})
    planner = BatchPlanner(cfg, make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    by_persona = {
        r.job_key.split("-")[1]: 0 for r in (await db.execute(select(MediaJob))).scalars().all()
    }
    for r in (await db.execute(select(MediaJob))).scalars().all():
        by_persona[r.job_key.split("-")[1]] += 1
    assert by_persona == {"alpha": 3, "beta": 6}  # A honored her override, B the default


async def test_fr_011_09_02_edited_budget_no_code_change(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    # a plain data edit to the config changes the outcome — no code path is touched
    cfg = BatchPlanConfig(shots_per_slot=2)
    planner = BatchPlanner(cfg, make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    m1 = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert m1.jobs_enqueued == 2


# ═══ FR-011-10 — coordinates GPU handoff with chat model ════════════════════════════════════════


async def test_fr_011_10_01_batch_requests_chat_unload_first(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    settings = make_settings(tmp_path)
    handoff = RecordingHandoff()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), settings,
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.run_nightly(sessionmaker, ImageRunner(settings, FakeBackend(), handoff),
                              now=night(3), target_date=TARGET_DATE)
    assert handoff.events[0] == "chat_unloaded"  # chat model out before any generation


async def test_fr_011_10_02_batch_signals_chat_reload_after(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    settings = make_settings(tmp_path)
    handoff = RecordingHandoff()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), settings,
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.run_nightly(sessionmaker, ImageRunner(settings, FakeBackend(), handoff),
                              now=night(3), target_date=TARGET_DATE)
    assert handoff.events[-1] == "chat_reloaded"  # chat model brought back after teardown


# ═══ FR-011-11 — progress/outcome observable ════════════════════════════════════════════════════


async def test_fr_011_11_01_counts_logged(sessionmaker, db, tmp_path, caplog):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe. 20:00 home.")
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    with caplog.at_level("INFO"):
        metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    snap = metrics.snapshot()
    assert (snap["slots_planned"], snap["shots_planned"], snap["jobs_enqueued"]) == (2, 4, 4)
    assert "F-011 batch planned" in caplog.text
    assert snap["per_persona"][0]["slug"] == "testgirl"


# ═══ NFR-011-01 — freshness (same-day) ══════════════════════════════════════════════════════════


async def test_nfr_011_01_01_assets_same_day_not_recycled(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    settings = make_settings(tmp_path)
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), settings,
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    await ImageRunner(settings, FakeBackend(), RecordingHandoff()).run_batch(
        sessionmaker, now=night(3))
    today = datetime.now(timezone.utc).date()
    assets = (await db.execute(select(MediaAsset))).scalars().all()
    assert assets and all(a.created_at.date() == today for a in assets)  # freshly generated today


# ═══ NFR-011-02 — coverage (no empty slots) ═════════════════════════════════════════════════════


async def test_nfr_011_02_01_each_slot_has_minimum_shots(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p)  # 5 slots
    await db.commit()
    n = 4
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=n), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    per_slot: dict[int, int] = {}
    for r in (await db.execute(select(MediaJob))).scalars().all():
        slot_idx = int(r.job_key.split("-")[-2])
        per_slot[slot_idx] = per_slot.get(slot_idx, 0) + 1
    assert len(per_slot) == 5 and all(c >= n for c in per_slot.values())  # no empty slot


def test_nfr_011_02_02_day_covered_morning_to_night():
    pytest.skip("TC-NFR-011-02-02: real-run coverage review on the GPU — benchmark/manual")


# ═══ NFR-011-03 — GPU exclusivity (CRITICAL) ════════════════════════════════════════════════════


async def test_nfr_011_03_01_refuses_when_chat_resident(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    settings = make_settings(tmp_path)
    handoff = RecordingHandoff()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), settings,
                           author=FakeAuthor(), references=FixedRefProvider([]))
    # daytime → chat model is resident → the batch must wait, not run
    result = await planner.run_nightly(
        sessionmaker, ImageRunner(settings, FakeBackend(), handoff),
        now=night(15), target_date=TARGET_DATE)
    assert result["ran"] is False
    assert handoff.events == []  # never touched the GPU handoff
    assert await queue_ops.pending_count(db) == 0  # nothing even enqueued while chat is up


async def test_nfr_011_03_02_handoff_unloads_chat(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    settings = make_settings(tmp_path)
    handoff = RecordingHandoff()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), settings,
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.run_nightly(sessionmaker, ImageRunner(settings, FakeBackend(), handoff),
                              now=night(3), target_date=TARGET_DATE)
    assert "chat_unloaded" in handoff.events  # chat model unloaded for the batch


# ═══ NFR-011-04 — resumability without duplication/corruption ═══════════════════════════════════


async def test_nfr_011_04_01_repeated_interruptions_no_duplication(sessionmaker, db, tmp_path):
    p = await make_persona(db)
    await make_plan(db, p, plan_text="08:00 gym. 13:00 office. 20:00 home.")
    await db.commit()
    settings = make_settings(tmp_path)
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=1), settings,
                           author=FakeAuthor(), references=FixedRefProvider([]))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    # crash twice, re-plan (idempotent) between, then finish
    with pytest.raises(RuntimeError):
        await ImageRunner(settings, CrashOnSecondBackend(), RecordingHandoff()).run_batch(
            sessionmaker, now=night(3))
    await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)  # re-plan: no dup
    with pytest.raises(RuntimeError):
        await ImageRunner(settings, CrashOnSecondBackend(), RecordingHandoff()).run_batch(
            sessionmaker, now=night(3))
    await ImageRunner(settings, FakeBackend(), RecordingHandoff()).run_batch(
        sessionmaker, now=night(3))
    assert await db.scalar(select(func.count()).select_from(MediaJob)) == 3       # 3 jobs, ever
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 3     # 3 assets, no dup
    report = await store.reconcile(db, tmp_path / "media")
    assert report == {"rows_missing_file": [], "files_missing_row": []}


# ═══ NFR-011-05 — throughput within the window ══════════════════════════════════════════════════


def test_nfr_011_05_01_throughput_within_budget():
    pytest.skip("TC-NFR-011-05-01: GPU throughput benchmark — measured out-of-band (F-008 report)")


# ═══ NFR-011-06 — config-driven budgets ═════════════════════════════════════════════════════════


async def test_nfr_011_06_01_edited_budgets_honored(sessionmaker, db, tmp_path):
    p = await make_persona(db, "Alina")
    await make_plan(db, p, plan_text="09:00 cafe.")
    await db.commit()
    author, refs = FakeAuthor(), FixedRefProvider([])
    lo = BatchPlanner(BatchPlanConfig(shots_per_slot=6, per_persona={"alina": {"shots_per_slot": 2}}),
                      make_settings(tmp_path), author=author, references=refs)
    m = await lo.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    assert m.jobs_enqueued == 2  # the per-persona override (data only) took effect


# ═══ NFR-011-07 — per-persona isolation ═════════════════════════════════════════════════════════


async def test_nfr_011_07_01_one_persona_failure_others_complete(sessionmaker, db, tmp_path):
    a = await make_persona(db, "Alpha")
    b = await make_persona(db, "Beta")
    await make_plan(db, a, plan_text="09:00 cafe.")
    await make_plan(db, b, plan_text="09:00 cafe.")
    await db.commit()
    # the reference provider blows up for Alpha only — Beta's archive must still be planned
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), make_settings(tmp_path),
                           author=FakeAuthor(), references=FailRefProvider("alpha"))
    metrics = await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)
    by_slug = {r.slug: r for r in metrics.per_persona}
    assert by_slug["alpha"].failed is True and by_slug["beta"].failed is False
    assert by_slug["beta"].jobs_enqueued == 2
    assert metrics.personas_failed == 1 and metrics.personas_planned == 1


# ═══ NFR-011-08 — observability ═════════════════════════════════════════════════════════════════


async def test_nfr_011_08_01_per_run_metrics_logged(sessionmaker, db, tmp_path):
    a = await make_persona(db, "Alpha")
    b = await make_persona(db, "Beta")
    await make_plan(db, a, plan_text="09:00 cafe.")
    await make_plan(db, b, plan_text="09:00 cafe. 20:00 home.")
    await db.commit()
    planner = BatchPlanner(BatchPlanConfig(shots_per_slot=2), make_settings(tmp_path),
                           author=FakeAuthor(), references=FixedRefProvider([]))
    snap = (await planner.plan_day(sessionmaker, now=night(3), target_date=TARGET_DATE)).snapshot()
    assert snap["planned_at"] is not None
    assert snap["personas_planned"] == 2
    assert len(snap["per_persona"]) == 2
    assert snap["jobs_enqueued"] == 6  # Alpha 1 slot×2 + Beta 2 slots×2


# ═══ default author / reference provider (standalone-run sanity) ════════════════════════════════


def test_default_author_produces_sfw_prompt_and_tags():
    author = DefaultPromptAuthor()
    ctx = SlotContext(0, "morning", "morning run", "gym", "07:00", "morning run at the gym")

    class _P:
        name = "Testgirl"

    shot = author.author(_P(), ctx, 0)
    assert "SFW" in shot.prompt and "Testgirl" in shot.prompt
    assert shot.slot.time_of_day == "morning" and shot.slot.location == "gym"


def test_default_reference_provider_uses_persona_refs():
    class _P:
        face_ref = "media/x/reference/face.png"
        fullbody_ref = None

    refs = DefaultReferenceProvider().references_for(_P())
    assert refs == ["media/x/reference/face.png"]  # only the anchors that exist


# ═══ User-story acceptance (manual/GPU) ═════════════════════════════════════════════════════════


@pytest.mark.parametrize("tc", [
    "TC-US-011-01-01 fresh same-day photos every day, no recycling",
    "TC-US-011-02-01 coverage morning→night; a fitting shot at any hour",
    "TC-US-011-03-01 operator: generation runs overnight on the freed GPU",
    "TC-US-011-04-01 operator: crash mid-batch resumes cleanly",
    "TC-US-011-05-01 B1: per-persona shots/slot configurable",
])
def test_us_011_manual_gpu_acceptance(tc):
    pytest.skip(f"{tc} — manual GPU/real-device acceptance, run out-of-band")
