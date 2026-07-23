"""F-008 Image Generation Runner tests — one runnable test per declared TC.

Maps 1:1 to `developer files/tests/F-008-image-generation-runner.md`. The engine + job lifecycle
run for real against a deterministic FakeBackend (services/imagegen/testing.py) with tmp media
roots and the shared in-memory DB; GPU/benchmark/human-judged and manual-e2e TCs are explicit
skips (same discipline as the rest of the suite). Realism itself was judged by the A/B benchmark
(developer files/image_benchmark_report.md — verdict: Rapid-AIO v23).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from services.bot.models import (
    MediaAsset,
    MediaJob,
    MediaJobStatus,
    MediaKind,
    Persona,
)
from services.bot.personas_seed import persona_slug
from services.imagegen import queue_ops, store
from services.imagegen.backends import ComfyUIBackend, GenerationFailed, build_backend
from services.imagegen.config import ImageRunnerSettings
from services.imagegen.contract import GenerationJob, GenParams, InvalidJob, SlotMeta
from services.imagegen.runner import ImageRunner, check_empty_archive_alert, in_media_window
from services.imagegen.testing import AlwaysFailBackend, FakeBackend, RecordingHandoff

IMAGEGEN_DIR = Path(__file__).resolve().parent.parent / "services" / "imagegen"
BOT_DIR = Path(__file__).resolve().parent.parent / "services" / "bot"


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────


def make_settings(tmp_path: Path, **overrides) -> ImageRunnerSettings:
    base = dict(
        backend="fake",
        media_root=str(tmp_path / "media"),
        backoff_base_s=0.0,       # retries become due immediately inside one drain
        stale_running_s=0.0,      # resume requeues stuck jobs instantly
        max_attempts=3,
        window_start_hour=1,
        window_end_hour=8,
    )
    base.update(overrides)
    return ImageRunnerSettings(**base)


async def make_persona(db, name: str = "Testgirl", tz: str = "UTC") -> Persona:
    p = Persona(name=name, timezone=tz)
    db.add(p)
    await db.flush()
    return p


def make_job(key: str = "job-1", slug: str = "testgirl", **overrides) -> GenerationJob:
    fields = dict(
        job_key=key,
        persona_slug=slug,
        prompt="a casual selfie at the gym",
        references=["media/testgirl/reference/face.png"],
        params=GenParams(steps=4, seed=7),
        slot=SlotMeta(pose="mirror selfie", background="gym", location="gym",
                      activity="workout", time_of_day="morning"),
    )
    fields.update(overrides)
    return GenerationJob(**fields)


def night(hour: int = 3) -> datetime:
    return datetime(2026, 7, 17, hour, 0, tzinfo=timezone.utc)


async def run_batch(runner: ImageRunner, sessionmaker, now: datetime | None = None) -> dict:
    return await runner.run_batch(sessionmaker, now=now or night())


def _imagegen_sources() -> str:
    return "\n".join(p.read_text() for p in IMAGEGEN_DIR.glob("*.py"))


# ═══ FR-008-01 — fixed job API ══════════════════════════════════════════════════════════════════


async def test_fr_008_01_01_valid_job_accepted_and_queued(db):
    persona = await make_persona(db)
    row = await queue_ops.enqueue(db, persona.id, make_job())
    assert row.status == MediaJobStatus.pending
    assert row.job_key == "job-1"


def test_fr_008_01_02_callers_use_contract_not_model_code():
    # The caller-facing modules must not touch model internals (§6.2c): no torch/diffusers/
    # ComfyUI HTTP details outside backends.py.
    for mod in ("contract.py", "queue_ops.py", "store.py"):
        src = (IMAGEGEN_DIR / mod).read_text()
        for banned in ("import torch", "diffusers", "comfyui", "urllib.request"):
            assert banned not in src, f"{mod} leaks model internals: {banned}"


def test_fr_008_01_03_malformed_job_rejected_cleanly():
    with pytest.raises(InvalidJob):
        GenerationJob.from_dict({"persona_slug": "x", "prompt": "p"})  # no job_key
    with pytest.raises(InvalidJob):
        GenerationJob.from_dict({"job_key": "k", "persona_slug": "x"})  # no prompt
    with pytest.raises(InvalidJob):
        GenerationJob.from_json("not json at all {")
    with pytest.raises(InvalidJob):
        GenerationJob.from_dict(
            {"job_key": "k", "persona_slug": "x", "prompt": "p", "params": {"steps": 0}})


# ═══ FR-008-02 — persona-agnostic ═══════════════════════════════════════════════════════════════


async def test_fr_008_02_01_generates_for_any_persona_from_payload(sessionmaker, db, tmp_path):
    p1 = await make_persona(db, "Alpha")
    p2 = await make_persona(db, "Beta")
    await queue_ops.enqueue(db, p1.id, make_job("k1", persona_slug(p1.name)))
    await queue_ops.enqueue(db, p2.id, make_job("k2", persona_slug(p2.name)))
    await db.commit()
    runner = ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff())
    await run_batch(runner, sessionmaker)
    root = tmp_path / "media"
    assert (root / "alpha" / "photos" / "MED-alpha-00001.png").exists()
    assert (root / "beta" / "photos" / "MED-beta-00001.png").exists()


def test_fr_008_02_02_no_persona_hardcoded():
    src = _imagegen_sources().lower()
    for seeded_name in ("алина", "alina", "kira", "кира", "мия", "mia"):
        assert f'"{seeded_name}"' not in src and f"'{seeded_name}'" not in src


# ═══ FR-008-03 — model swappable behind the fixed API ═══════════════════════════════════════════


async def test_fr_008_03_01_same_job_runs_on_model_a_and_b(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("swap-a"))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(name="fake-A"),
                                RecordingHandoff()), sessionmaker)
    await queue_ops.enqueue(db, persona.id, make_job("swap-b"))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(name="fake-B"),
                                RecordingHandoff()), sessionmaker)
    assets = (await db.execute(select(MediaAsset))).scalars().all()
    assert len(assets) == 2  # both models produced a valid asset via the same contract


def test_fr_008_03_02_model_chosen_by_config(tmp_path):
    assert isinstance(build_backend(make_settings(tmp_path, backend="fake")), FakeBackend)
    assert isinstance(
        build_backend(make_settings(tmp_path, backend="comfyui-aio")), ComfyUIBackend)
    with pytest.raises(ValueError):
        build_backend(make_settings(tmp_path, backend="no-such-model"))


async def test_fr_008_03_03_swap_leaves_job_and_asset_schema_unchanged(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    payload = make_job("schema-a").to_json()
    await queue_ops.enqueue(db, persona.id, GenerationJob.from_json(payload))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(name="fake-A"),
                                RecordingHandoff()), sessionmaker)
    a1 = await db.scalar(select(MediaAsset))
    fields_a = {c.name for c in MediaAsset.__table__.columns}
    # swap model; the SAME payload shape (different key) must be accepted, same row schema
    await queue_ops.enqueue(
        db, persona.id, GenerationJob.from_json(payload.replace("schema-a", "schema-b")))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(name="fake-B"),
                                RecordingHandoff()), sessionmaker)
    a2 = (await db.execute(
        select(MediaAsset).where(MediaAsset.id != a1.id))).scalar_one()
    assert {c.name for c in MediaAsset.__table__.columns} == fields_a
    assert a2.kind == a1.kind and a2.storage_ref.startswith("media/")


# ═══ FR-008-04 — low distilled step count ═══════════════════════════════════════════════════════


async def test_fr_008_04_01_image_produced_at_4_8_steps(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    for i, steps in enumerate((4, 6, 8)):
        await queue_ops.enqueue(
            db, persona.id, make_job(f"steps-{steps}", params=GenParams(steps=steps, seed=i)))
    await db.commit()
    backend = FakeBackend()
    await run_batch(ImageRunner(make_settings(tmp_path), backend, RecordingHandoff()),
                    sessionmaker)
    assert sorted(j.params.steps for j in backend.generate_calls) == [4, 6, 8]
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 3


async def test_fr_008_04_02_step_count_honored_exactly(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("s4", params=GenParams(steps=4)))
    await queue_ops.enqueue(db, persona.id, make_job("s8", params=GenParams(steps=8, seed=1)))
    await db.commit()
    backend = FakeBackend()
    await run_batch(ImageRunner(make_settings(tmp_path), backend, RecordingHandoff()),
                    sessionmaker)
    by_key = {j.job_key: j.params.steps for j in backend.generate_calls}
    assert by_key == {"s4": 4, "s8": 8}  # exactly what each job asked, no clamping/hard-code


# ═══ FR-008-05 — reference forwarded as conditioning ════════════════════════════════════════════


async def test_fr_008_05_01_reference_forwarded_to_model(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    refs = ["media/testgirl/reference/face.png", "media/testgirl/reference/body.png"]
    await queue_ops.enqueue(db, persona.id, make_job("ref-1", references=refs))
    await db.commit()
    backend = FakeBackend()
    await run_batch(ImageRunner(make_settings(tmp_path), backend, RecordingHandoff()),
                    sessionmaker)
    assert backend.generate_calls[0].references == refs  # F-009's refs reach the model untouched


def test_fr_008_05_02_missing_reference_defined_behavior(tmp_path):
    # The production backend rejects a reference-less job with a DEFINED retryable error —
    # no crash, no silent text-to-image (config would have to enable that path explicitly).
    backend = ComfyUIBackend(make_settings(tmp_path, backend="comfyui-aio"))
    with pytest.raises(GenerationFailed, match="no reference"):
        backend._stage_references(make_job("no-ref", references=[]))


# ═══ FR-008-06 — params from job/config, not hard-coded ═════════════════════════════════════════


async def test_fr_008_06_01_all_params_read_from_job(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    params = GenParams(steps=6, cfg=1.5, width=768, height=512, seed=99, negative="blurry")
    await queue_ops.enqueue(db, persona.id, make_job("params-1", params=params))
    await db.commit()
    backend = FakeBackend()
    await run_batch(ImageRunner(make_settings(tmp_path), backend, RecordingHandoff()),
                    sessionmaker)
    got = backend.generate_calls[0].params
    assert (got.steps, got.cfg, got.width, got.height, got.seed, got.negative) == \
        (6, 1.5, 768, 512, 99, "blurry")


def test_fr_008_06_02_no_inline_hardcoded_params():
    # The engine paths must not bake in generation numbers: contract defaults + config carry them.
    runner_src = (IMAGEGEN_DIR / "runner.py").read_text()
    for banned in ("steps=4", "steps=8", "cfg=1.0", "width=1024"):
        assert banned not in runner_src


async def test_fr_008_06_03_fixed_seed_reproducible(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    same = dict(params=GenParams(steps=4, seed=42))
    await queue_ops.enqueue(db, persona.id, make_job("repro-1", **same))
    await queue_ops.enqueue(db, persona.id, make_job("repro-2", **same))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    root = tmp_path / "media" / "testgirl" / "photos"
    files = sorted(root.glob("*.png"))
    assert len(files) == 2
    assert files[0].read_bytes() == files[1].read_bytes()  # same seed+params → same image


# ═══ FR-008-07 — MED-id file 1:1 with the row ═══════════════════════════════════════════════════


async def test_fr_008_07_01_file_under_media_slug_photos_named_med_id(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job())
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    assert (tmp_path / "media" / "testgirl" / "photos" / "MED-testgirl-00001.png").exists()


async def test_fr_008_07_02_file_stem_equals_asset_id(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job())
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    asset = (await db.execute(select(MediaAsset))).scalar_one()
    assert asset.id == "MED-testgirl-00001"
    assert asset.storage_ref == "media/testgirl/photos/MED-testgirl-00001.png"
    stored = tmp_path / "media" / "testgirl" / "photos" / f"{asset.id}.png"
    assert stored.stem == asset.id and stored.exists()


async def test_fr_008_07_03_exactly_one_file_per_row(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    for i in range(4):
        await queue_ops.enqueue(db, persona.id, make_job(f"n-{i}", params=GenParams(seed=i)))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    report = await store.reconcile(db, tmp_path / "media")
    assert report == {"rows_missing_file": [], "files_missing_row": []}
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 4
    assert len(list((tmp_path / "media").glob("*/photos/*.png"))) == 4


# ═══ FR-008-08 — MEDIA_ASSET metadata ═══════════════════════════════════════════════════════════


async def test_fr_008_08_01_row_carries_kind_intimacy_storage_meta(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(
        db, persona.id, make_job("meta-1", intimate=True, intimacy_level=2))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    asset = (await db.execute(select(MediaAsset))).scalar_one()
    assert asset.kind == MediaKind.photo
    assert asset.intimate is True and asset.intimacy_level == 2
    assert asset.storage_ref.startswith("media/testgirl/photos/")
    assert asset.meta_json


async def test_fr_008_08_02_meta_json_has_all_five_slot_fields(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job())
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    meta = store.parse_meta((await db.execute(select(MediaAsset))).scalar_one())
    assert {"pose", "background", "location", "activity", "time_of_day"} <= meta.keys()
    assert meta["activity"] == "workout" and meta["time_of_day"] == "morning"
    assert meta["prompt"]  # provenance (F-010 FR-010-08 hand-off)


# ═══ FR-008-09 — atomic writes ══════════════════════════════════════════════════════════════════


def test_fr_008_09_01_interrupted_write_leaves_no_visible_partial(tmp_path, monkeypatch):
    target = tmp_path / "media" / "g" / "photos" / "MED-g-00001.png"

    def boom(fd):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr("services.imagegen.store.os.fsync", boom)
    with pytest.raises(OSError):
        store.atomic_write(target, b"x" * 1024)
    # the archive scan (finished assets = *.png) sees nothing — the partial is a .part temp
    assert list(target.parent.glob("*.png")) == []


def test_fr_008_09_02_temp_then_rename_used(tmp_path):
    target = tmp_path / "a" / "b.png"
    store.atomic_write(target, b"data")
    assert target.read_bytes() == b"data"
    assert list(target.parent.glob("*.part")) == []  # temp cleaned up by the rename
    src = (IMAGEGEN_DIR / "store.py").read_text()
    assert "os.replace" in src  # atomic rename, not shutil.move/plain write


async def test_fr_008_09_03_no_row_before_durable_file(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("fail-all"))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path, max_attempts=2),
                                AlwaysFailBackend(), RecordingHandoff()), sessionmaker)
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 0
    assert list((tmp_path / "media").glob("**/*.png")) == []


# ═══ FR-008-10 — writes only, never serves, never hot path ══════════════════════════════════════


def test_fr_008_10_01_runner_has_no_user_serving_path():
    src = _imagegen_sources()
    assert "aiogram" not in src  # no Telegram sending from the engine
    assert "send_photo" not in src and "answer(" not in src
    public = [n for n in dir(ImageRunner) if not n.startswith("_")]
    assert not any("send" in n or "serve" in n for n in public)


def test_fr_008_10_02_reply_turn_never_invokes_the_runner():
    # The bot's turn pipeline must not import the engine — generation is batch-only (§3.2).
    assert "imagegen" not in (BOT_DIR / "orchestrator.py").read_text()
    for handler_file in (BOT_DIR / "handlers").glob("*.py"):
        assert "imagegen" not in handler_file.read_text(), handler_file.name


# ═══ FR-008-11 — scheduled night batch ══════════════════════════════════════════════════════════


async def test_fr_008_11_01_jobs_drained_during_sleep_window(sessionmaker, db, tmp_path):
    persona = await make_persona(db, tz="UTC")
    await queue_ops.enqueue(db, persona.id, make_job())
    await db.commit()
    runner = ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff())
    assert await runner.should_run(sessionmaker, now=night(3)) is True
    await run_batch(runner, sessionmaker, now=night(3))
    assert await queue_ops.pending_count(db) == 0


async def test_fr_008_11_02_no_batch_during_awake_hours(sessionmaker, db, tmp_path):
    persona = await make_persona(db, tz="UTC")
    await queue_ops.enqueue(db, persona.id, make_job())
    await db.commit()
    runner = ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff())
    assert await runner.should_run(sessionmaker, now=night(15)) is False  # 15:00 = serving hours
    assert in_media_window(night(15), "UTC", runner.settings) is False
    # persona-local window: 03:00 UTC is daytime in Tokyo (12:00) — her window is closed
    assert in_media_window(night(3), "Asia/Tokyo", runner.settings) is False


# ═══ FR-008-12 — idempotent by job key ══════════════════════════════════════════════════════════


async def test_fr_008_12_01_rerunning_done_job_no_duplicate(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("idem-1"))
    await db.commit()
    settings = make_settings(tmp_path)
    await run_batch(ImageRunner(settings, FakeBackend(), RecordingHandoff()), sessionmaker)
    # same key enqueued again → the existing done row is returned, nothing new to claim
    await queue_ops.enqueue(db, persona.id, make_job("idem-1"))
    await db.commit()
    await run_batch(ImageRunner(settings, FakeBackend(), RecordingHandoff()), sessionmaker)
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 1
    assert await db.scalar(select(func.count()).select_from(MediaJob)) == 1


async def test_fr_008_12_02_redelivery_deduped(db):
    persona = await make_persona(db)
    r1 = await queue_ops.enqueue(db, persona.id, make_job("dup-key"))
    r2 = await queue_ops.enqueue(db, persona.id, make_job("dup-key"))
    assert r1.id == r2.id  # one row, not two


async def test_fr_008_12_03_two_workers_one_job_single_winner(sessionmaker, db):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("race-1"))
    await db.commit()
    async with sessionmaker() as s1, sessionmaker() as s2:
        first = await queue_ops.claim_next(s1)
        await s1.commit()
        second = await queue_ops.claim_next(s2)
        await s2.commit()
    assert first is not None
    assert second is None  # the guarded UPDATE let exactly one claimer win


# ═══ FR-008-13 — retry with backoff, degrade ════════════════════════════════════════════════════


async def test_fr_008_13_01_transient_failure_retried_then_succeeds(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("flaky"))
    await db.commit()
    backend = FakeBackend(fail_times=1)
    await run_batch(ImageRunner(make_settings(tmp_path), backend, RecordingHandoff()),
                    sessionmaker)
    row = (await db.execute(select(MediaJob))).scalar_one()
    assert row.status == MediaJobStatus.done and row.attempts == 1
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 1


async def test_fr_008_13_02_permanent_failure_logged_skipped_no_partial(
    sessionmaker, db, tmp_path, caplog
):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("doomed"))
    await db.commit()
    with caplog.at_level("ERROR"):
        await run_batch(ImageRunner(make_settings(tmp_path, max_attempts=2),
                                    AlwaysFailBackend(), RecordingHandoff()), sessionmaker)
    row = (await db.execute(select(MediaJob))).scalar_one()
    assert row.status == MediaJobStatus.failed and row.attempts == 2
    assert row.error
    assert "gave up" in caplog.text
    assert list((tmp_path / "media").glob("**/*.png")) == []


async def test_fr_008_13_03_one_failure_does_not_block_batch(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("ok-1", params=GenParams(seed=1)))
    await queue_ops.enqueue(db, persona.id, make_job("bad", params=GenParams(seed=2)))
    await queue_ops.enqueue(db, persona.id, make_job("ok-2", params=GenParams(seed=3)))
    await db.commit()

    class FailOneBackend(FakeBackend):
        def generate(self, job):
            if job.job_key == "bad":
                self.generate_calls.append(job)
                raise GenerationFailed("this one always dies")
            return super().generate(job)

    await run_batch(ImageRunner(make_settings(tmp_path, max_attempts=2),
                                FailOneBackend(), RecordingHandoff()), sessionmaker)
    statuses = {
        r.job_key: r.status for r in (await db.execute(select(MediaJob))).scalars().all()
    }
    assert statuses["ok-1"] == MediaJobStatus.done
    assert statuses["ok-2"] == MediaJobStatus.done
    assert statuses["bad"] == MediaJobStatus.failed


# ═══ FR-008-14 — resumable batch ════════════════════════════════════════════════════════════════


class CrashOnSecondBackend(FakeBackend):
    """First job fine, second job crashes the whole process (not a normal model error)."""

    def generate(self, job):
        if len(self.generate_calls) >= 1:
            self.generate_calls.append(job)
            raise RuntimeError("simulated process crash")
        return super().generate(job)


async def test_fr_008_14_01_interrupted_batch_resumes(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    for i in range(3):
        await queue_ops.enqueue(db, persona.id, make_job(f"r-{i}", params=GenParams(seed=i)))
    await db.commit()
    settings = make_settings(tmp_path)
    crashing = CrashOnSecondBackend()
    with pytest.raises(RuntimeError):
        await run_batch(ImageRunner(settings, crashing, RecordingHandoff()), sessionmaker)
    # resume: stale running row is requeued and the remaining jobs complete
    await run_batch(ImageRunner(settings, FakeBackend(), RecordingHandoff()), sessionmaker)
    statuses = [r.status for r in (await db.execute(select(MediaJob))).scalars().all()]
    assert statuses.count(MediaJobStatus.done) == 3
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 3


async def test_fr_008_14_02_done_jobs_not_redone_on_resume(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    for i in range(2):
        await queue_ops.enqueue(db, persona.id, make_job(f"d-{i}", params=GenParams(seed=i)))
    await db.commit()
    settings = make_settings(tmp_path)
    await run_batch(ImageRunner(settings, FakeBackend(), RecordingHandoff()), sessionmaker)
    resumed_backend = FakeBackend()
    await run_batch(ImageRunner(settings, resumed_backend, RecordingHandoff()), sessionmaker)
    assert resumed_backend.generate_calls == []  # nothing regenerated
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 2


# ═══ FR-008-15 — GPU held only when chat unloaded ═══════════════════════════════════════════════


class OrderedBackend(FakeBackend):
    """Shares an event list with the handoff to assert global ordering."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    def load(self) -> None:
        super().load()
        self.events.append("image_loaded")

    def close(self) -> None:
        super().close()
        self.events.append("image_released")


class OrderedHandoff(RecordingHandoff):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events


async def _ordered_run(sessionmaker, db, tmp_path, backend_cls=OrderedBackend):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("order-1"))
    await db.commit()
    events: list[str] = []
    runner = ImageRunner(make_settings(tmp_path), backend_cls(events), OrderedHandoff(events))
    return events, runner


async def test_fr_008_15_01_chat_unloaded_before_image_loads(sessionmaker, db, tmp_path):
    events, runner = await _ordered_run(sessionmaker, db, tmp_path)
    await run_batch(runner, sessionmaker)
    assert events.index("chat_unloaded") < events.index("image_loaded")


async def test_fr_008_15_02_image_released_before_chat_reloads(sessionmaker, db, tmp_path):
    events, runner = await _ordered_run(sessionmaker, db, tmp_path)
    await run_batch(runner, sessionmaker)
    assert events.index("image_released") < events.index("chat_reloaded")


async def test_fr_008_15_03_never_both_resident(sessionmaker, db, tmp_path):
    events, runner = await _ordered_run(sessionmaker, db, tmp_path)
    await run_batch(runner, sessionmaker)
    # chat is "resident" before chat_unloaded and after chat_reloaded; image between load/release —
    # the full ordering proves single ownership at every point of the run
    assert events == ["chat_unloaded", "image_loaded", "image_released", "chat_reloaded"]


# ═══ FR-008-16 — clean bring-up / tear-down ═════════════════════════════════════════════════════


async def test_fr_008_16_01_gpu_released_after_batch(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job())
    await db.commit()
    backend = FakeBackend()
    runner = ImageRunner(make_settings(tmp_path), backend, RecordingHandoff())
    await run_batch(runner, sessionmaker)
    assert backend.closed is True and backend.loaded is False
    assert runner.metrics.snapshot()["torn_down"] is True


async def test_fr_008_16_02_crash_still_frees_gpu(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    for i in range(2):
        await queue_ops.enqueue(db, persona.id, make_job(f"c-{i}", params=GenParams(seed=i)))
    await db.commit()
    backend = CrashOnSecondBackend()
    handoff = RecordingHandoff()
    with pytest.raises(RuntimeError):
        await run_batch(ImageRunner(make_settings(tmp_path), backend, handoff), sessionmaker)
    assert backend.closed is True                # teardown ran despite the crash
    assert "chat_reloaded" in handoff.events     # and the chat model was still brought back


# ═══ NFR-008-01 — realism (benchmark/human-judged) ══════════════════════════════════════════════


def test_nfr_008_01_01_ab_realism_benchmark():
    pytest.skip("TC-NFR-008-01-01: GPU A/B benchmark — done via image/benchmark.py; verdict "
                "Rapid-AIO v23 (developer files/image_benchmark_report.md)")


def test_nfr_008_01_02_human_realism_acceptance():
    pytest.skip("TC-NFR-008-01-02: human scrutiny of hands/skin/background — manual acceptance")


# ═══ NFR-008-02 — batch fits the sleep window ═══════════════════════════════════════════════════


def test_nfr_008_02_01_per_image_latency_measured():
    pytest.skip("TC-NFR-008-02-01: GPU performance run — measured by the benchmark: "
                "avg 117 s/img at 4 steps/1024² (report)")


def test_nfr_008_02_02_full_day_archive_fits_window():
    pytest.skip("TC-NFR-008-02-02: load test on the real GPU night window — out-of-band")


# ═══ NFR-008-03 — never an empty archive ════════════════════════════════════════════════════════


async def test_nfr_008_03_01_failed_batch_degrades_to_prior_day(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("old-1"))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    # age yesterday's asset, then tonight's batch fails completely
    asset = (await db.execute(select(MediaAsset))).scalar_one()
    asset.created_at = datetime.now(timezone.utc) - timedelta(days=1)
    await queue_ops.enqueue(db, persona.id, make_job("tonight"))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path, max_attempts=1),
                                AlwaysFailBackend(), RecordingHandoff()), sessionmaker)
    served = await store.latest_available_assets(db, persona.id)
    assert [a.id for a in served] == [asset.id]  # yesterday's archive, never nothing


async def test_nfr_008_03_02_empty_archive_alert_fires(sessionmaker, db, caplog):
    await make_persona(db, "Emptygirl")
    await db.commit()
    with caplog.at_level("ERROR"):
        empty = await check_empty_archive_alert(sessionmaker)
    assert empty  # the persona with no assets is flagged
    assert "empty media archive" in caplog.text


async def test_nfr_008_03_03_no_user_visible_gap(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job("seed-asset"))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    asset = (await db.execute(select(MediaAsset))).scalar_one()
    asset.created_at = datetime.now(timezone.utc) - timedelta(days=3)
    await db.commit()
    served = await store.latest_available_assets(db, persona.id)
    assert served, "a prior valid asset is served — no gap surfaces to the user"


# ═══ NFR-008-04 — off the reply hot path ════════════════════════════════════════════════════════


def test_nfr_008_04_01_reply_latency_unaffected():
    pytest.skip("TC-NFR-008-04-01: live performance measurement while a batch runs — out-of-band")


def test_nfr_008_04_02_no_inline_generation_in_reply_path():
    sources = [BOT_DIR / "orchestrator.py", BOT_DIR / "chat_client.py"]
    sources += list((BOT_DIR / "handlers").glob("*.py"))
    for mod in sources:
        src = mod.read_text()
        assert "imagegen" not in src and "ComfyUI" not in src, mod.name


# ═══ NFR-008-05 — referential integrity ═════════════════════════════════════════════════════════


async def test_nfr_008_05_01_every_row_has_its_file(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    for i in range(3):
        await queue_ops.enqueue(db, persona.id, make_job(f"ri-{i}", params=GenParams(seed=i)))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    report = await store.reconcile(db, tmp_path / "media")
    assert report["rows_missing_file"] == []


async def test_nfr_008_05_02_every_file_has_its_row(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    await queue_ops.enqueue(db, persona.id, make_job())
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()),
                    sessionmaker)
    # plant an orphan file the runner did not produce
    orphan = tmp_path / "media" / "testgirl" / "photos" / "MED-testgirl-99999.png"
    orphan.write_bytes(b"stray")
    report = await store.reconcile(db, tmp_path / "media")
    assert report["files_missing_row"] == [str(orphan)]


# ═══ NFR-008-06 — durability across restarts ════════════════════════════════════════════════════


async def test_nfr_008_06_01_assets_survive_restart(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine

    from services.bot.db import init_models, make_sessionmaker

    db_path = tmp_path / "media.sqlite3"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url)
    await init_models(engine)
    sm = make_sessionmaker(engine)
    async with sm() as db:
        persona = await make_persona(db)
        await queue_ops.enqueue(db, persona.id, make_job())
        await db.commit()
    await run_batch(
        ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff()), sm)
    await engine.dispose()  # "restart"
    engine2 = create_async_engine(url)
    sm2 = make_sessionmaker(engine2)
    async with sm2() as db:
        asset = (await db.execute(select(MediaAsset))).scalar_one()
        assert asset.id == "MED-testgirl-00001"
        assert (tmp_path / "media" / "testgirl" / "photos" / f"{asset.id}.png").exists()
    await engine2.dispose()


# ═══ NFR-008-07 — environment isolation ═════════════════════════════════════════════════════════


def test_nfr_008_07_01_runner_package_free_of_gpu_deps():
    # The orchestration package must be importable from the bot env: torch/CUDA live only in
    # the separate ComfyUI process (image/.venv).
    src = _imagegen_sources()
    for heavy in ("import torch", "from torch", "import diffusers", "from diffusers"):
        assert heavy not in src


def test_nfr_008_07_02_no_shared_env_conflict():
    pytest.skip("TC-NFR-008-07-02: multi-env install check (chat/.venv vs image/.venv) — "
                "verified operationally; envs are physically separate directories")


# ═══ NFR-008-08 — observability ═════════════════════════════════════════════════════════════════


async def test_nfr_008_08_01_metrics_exposed(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    for i in range(2):
        await queue_ops.enqueue(db, persona.id, make_job(f"m-{i}", params=GenParams(seed=i)))
    await db.commit()
    runner = ImageRunner(make_settings(tmp_path), FakeBackend(), RecordingHandoff())
    snapshot = await run_batch(runner, sessionmaker)
    assert snapshot["jobs_done"] == 2 and snapshot["jobs_given_up"] == 0
    assert snapshot["avg_gen_s"] >= 0.0
    assert snapshot["batch_started_at"] and snapshot["batch_finished_at"]
    assert snapshot["torn_down"] is True


async def test_nfr_008_08_02_alerts_on_empty_archive(sessionmaker, db, caplog):
    await make_persona(db, "Alertgirl")
    await db.commit()
    with caplog.at_level("ERROR"):
        flagged = await check_empty_archive_alert(sessionmaker)
    assert flagged and "ALERT" in caplog.text


# ═══ NFR-008-09 — swappability without regression ═══════════════════════════════════════════════


async def test_nfr_008_09_01_swap_keeps_contract_and_schema(sessionmaker, db, tmp_path):
    persona = await make_persona(db)
    payload = make_job("nr-1").to_json()
    await queue_ops.enqueue(db, persona.id, GenerationJob.from_json(payload))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(name="fake-A"),
                                RecordingHandoff()), sessionmaker)
    schema_before = {c.name: str(c.type) for c in MediaAsset.__table__.columns}
    await queue_ops.enqueue(
        db, persona.id, GenerationJob.from_json(payload.replace("nr-1", "nr-2")))
    await db.commit()
    await run_batch(ImageRunner(make_settings(tmp_path), FakeBackend(name="fake-B"),
                                RecordingHandoff()), sessionmaker)
    assert {c.name: str(c.type) for c in MediaAsset.__table__.columns} == schema_before
    assert await db.scalar(select(func.count()).select_from(MediaAsset)) == 2


# ═══ NFR-008-10 — config-driven, no redeploy ════════════════════════════════════════════════════


def test_nfr_008_10_01_model_steps_window_from_config(monkeypatch):
    monkeypatch.setenv("IMAGE_BACKEND", "fake")
    monkeypatch.setenv("IMAGE_DEFAULT_STEPS", "6")
    monkeypatch.setenv("IMAGE_WINDOW_START_HOUR", "2")
    monkeypatch.setenv("IMAGE_WINDOW_END_HOUR", "7")
    s = ImageRunnerSettings()
    assert (s.backend, s.default_steps, s.window_start_hour, s.window_end_hour) == \
        ("fake", 6, 2, 7)
    assert isinstance(build_backend(s), FakeBackend)  # takes effect without a code change


# ═══ User-story acceptance (manual GPU / real device) ═══════════════════════════════════════════


@pytest.mark.parametrize("tc", [
    "TC-US-008-01-01 operator: reliable overnight archive",
    "TC-US-008-02-01 A3: instant premium photo",
    "TC-US-008-03-01 A8 skeptic: survives scrutiny",
    "TC-US-008-04-01 operator: no empty archive, recovers",
    "TC-US-008-05-01 integrator: model swap, no caller change",
    "TC-US-008-06-01 infra: single GPU owner at the sleep/wake transition",
])
def test_us_008_manual_gpu_acceptance(tc):
    pytest.skip(f"{tc} — manual GPU/real-device acceptance, run out-of-band")
