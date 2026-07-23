"""The F-008 batch runner: window gate → GPU handoff → drain queue → clean teardown.

One nightly pass (architecture.md §6.1, DFD-3):
  1. the media window opens in the persona-roster's night (window gate, FR-008-11);
  2. the chat LLM is unloaded FIRST (handoff, FR-008-15) — one heavy model owns the 48GB GPU;
  3. the backend loads, jobs are claimed and executed one by one — a failure retries with backoff
     and never blocks the rest (FR-008-13); the same job key never produces twice (FR-008-12);
  4. teardown ALWAYS runs (finally) and the chat model is reloaded after — even on a crash the GPU
     is not left held (FR-008-16; the benchmark's leaked-47GB lesson, v0.39.2).

Never called from the reply hot path: nothing in services/bot imports this module (FR-008-10).
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.bot.models import MediaJobStatus, Persona
from services.imagegen import queue_ops, store
from services.imagegen.backends import GenerationFailed, ModelBackend, build_backend
from services.imagegen.config import ImageRunnerSettings
from services.imagegen.contract import GenerationJob, InvalidJob
from services.imagegen.retention import RetentionConfig, run_retention_all

log = logging.getLogger(__name__)


# ── GPU day/night handoff (§6.1, FR-008-15) ─────────────────────────────────────────────────────


class GpuHandoff(Protocol):
    """Unload the chat LLM before the image model loads; reload it after teardown."""

    async def unload_chat(self) -> None: ...
    async def reload_chat(self) -> None: ...


class CommandHandoff:
    """Prod handoff: run the configured shell commands (empty command = managed externally)."""

    def __init__(self, settings: ImageRunnerSettings) -> None:
        self._s = settings

    async def unload_chat(self) -> None:
        self._run(self._s.chat_unload_cmd)

    async def reload_chat(self) -> None:
        self._run(self._s.chat_reload_cmd)

    @staticmethod
    def _run(cmd: str) -> None:
        if cmd.strip():
            subprocess.run(cmd, shell=True, check=False, timeout=300)


# ── window gate (FR-008-11) ─────────────────────────────────────────────────────────────────────


def in_media_window(now: datetime, tz_name: str, settings: ImageRunnerSettings) -> bool:
    """True inside [window_start_hour, window_end_hour) of the given timezone's local clock —
    the persona's sleep half of the day/night schedule (§6.1). Wrapping windows supported."""
    try:
        local = now.astimezone(ZoneInfo(tz_name or "UTC"))
    except (KeyError, ValueError):
        local = now.astimezone(timezone.utc)
    h, start, end = local.hour, settings.window_start_hour, settings.window_end_hour
    if start == end:  # degenerate config → window always open (explicit operator choice)
        return True
    if start < end:
        return start <= h < end
    return h >= start or h < end  # wraps midnight


# ── metrics (NFR-008-08) ────────────────────────────────────────────────────────────────────────


@dataclass
class RunnerMetrics:
    jobs_done: int = 0
    jobs_failed_attempts: int = 0
    jobs_given_up: int = 0
    gen_seconds: list[float] = field(default_factory=list)
    batch_started_at: datetime | None = None
    batch_finished_at: datetime | None = None
    torn_down: bool = True
    # F-021 FR-021-12: the night's retention outcome travels with the batch metrics (§6.4).
    retention_evicted: int = 0
    retention_reports: list = field(default_factory=list)

    def snapshot(self) -> dict:
        avg = sum(self.gen_seconds) / len(self.gen_seconds) if self.gen_seconds else 0.0
        return {
            "jobs_done": self.jobs_done,
            "jobs_failed_attempts": self.jobs_failed_attempts,
            "jobs_given_up": self.jobs_given_up,
            "avg_gen_s": round(avg, 2),
            "batch_started_at": self.batch_started_at,
            "batch_finished_at": self.batch_finished_at,
            "torn_down": self.torn_down,
            "retention_evicted": self.retention_evicted,
            "retention_reports": list(self.retention_reports),
        }


# ── the runner ──────────────────────────────────────────────────────────────────────────────────


class ImageRunner:
    """Persona-agnostic batch engine over a swappable backend (FR-008-02/03)."""

    def __init__(
        self,
        settings: ImageRunnerSettings,
        backend: ModelBackend | None = None,
        handoff: GpuHandoff | None = None,
    ) -> None:
        self.settings = settings
        self.backend = backend or build_backend(settings)
        self.handoff = handoff or CommandHandoff(settings)
        self.metrics = RunnerMetrics()

    # -- one queue drain inside an open window --

    async def run_batch(
        self, sessionmaker: async_sessionmaker[AsyncSession], now: datetime | None = None
    ) -> dict:
        """Drain due jobs. Assumes the window gate was checked by the caller (`should_run`)."""
        now = now or datetime.now(timezone.utc)
        self.metrics.batch_started_at = now
        self.metrics.torn_down = False
        await self.handoff.unload_chat()          # chat model out FIRST (FR-008-15)
        try:
            self.backend.load()
            async with sessionmaker() as db:
                await queue_ops.requeue_stale(
                    db, stale_after_s=self.settings.stale_running_s, now=now)
                await db.commit()
            while True:
                async with sessionmaker() as db:
                    row = await queue_ops.claim_next(db, now=now)
                    if row is None:
                        await db.commit()
                        break
                    await db.commit()
                    await self._process_one(db, row, now=now)
                    await db.commit()
            # DFD-3: the night's rows have landed → retention runs against the archive as it will
            # actually be served, BEFORE wake reloads the chat model (FR-021-08 / D8). Never on the
            # reply hot path, and never allowed to break the media window.
            await self._run_retention(sessionmaker, now=now)
        finally:
            # teardown even on a crash — never leak the GPU into the day window (FR-008-16)
            self.backend.close()
            self.metrics.torn_down = True
            self.metrics.batch_finished_at = datetime.now(timezone.utc)
            await self.handoff.reload_chat()
        return self.metrics.snapshot()

    async def _run_retention(
        self, sessionmaker: async_sessionmaker[AsyncSession], now: datetime | None = None
    ) -> list:
        """F-021 retention across the roster, isolated from the batch's success (FR-021-08/10/12)."""
        if not self.settings.retention_enabled:
            return []
        cfg = RetentionConfig(
            cap=self.settings.retention_cap,
            floor=self.settings.retention_floor,
            grace_hours=self.settings.retention_grace_hours,
        )
        try:
            async with sessionmaker() as db:
                reports = await run_retention_all(db, self.settings.media_root, cfg, now)
                await db.commit()
        except Exception:  # a retention failure must never cost us the generated batch
            log.exception("retention pass failed")
            return []
        self.metrics.retention_evicted = sum(r.evicted for r in reports)
        self.metrics.retention_reports = [r.as_dict() for r in reports]
        return reports

    async def _process_one(self, db: AsyncSession, row, now: datetime | None = None) -> None:
        """One job: parse → generate → atomic store → done; failure → backoff retry (FR-008-13).

        `now` is the batch's logical clock — retries schedule against it so backoff math and the
        claim loop's due-check agree (a retry becomes claimable within the same drain once due).
        """
        try:
            job = GenerationJob.from_json(row.payload_json)
        except InvalidJob as exc:
            log.warning("job %s payload invalid: %s", row.job_key, exc)
            await queue_ops.mark_failed_attempt(
                db, row, f"invalid payload: {exc}",
                max_attempts=1, backoff_base_s=self.settings.backoff_base_s, now=now)
            self.metrics.jobs_given_up += 1
            return

        # Idempotency backstop (FR-008-12): a done job with an asset is never re-generated —
        # claim_next only hands out pending rows, but a redelivered duplicate lands here too.
        if row.status == MediaJobStatus.done and row.asset_id:
            return

        persona = await db.scalar(select(Persona).where(Persona.id == row.persona_id))
        if persona is None:
            await queue_ops.mark_failed_attempt(
                db, row, "persona not found",
                max_attempts=1, backoff_base_s=self.settings.backoff_base_s, now=now)
            self.metrics.jobs_given_up += 1
            return

        # Jitter the seed by the attempt count so a retry never re-rolls the SAME (possibly
        # NaN-producing) seed — a black-frame failure must self-heal, not loop deterministically.
        if row.attempts:
            job.params.seed += 1000 * row.attempts

        t0 = time.monotonic()
        try:
            image_bytes = await asyncio.to_thread(self.backend.generate, job)
        except GenerationFailed as exc:
            self.metrics.jobs_failed_attempts += 1
            await queue_ops.mark_failed_attempt(
                db, row, str(exc),
                max_attempts=self.settings.max_attempts,
                backoff_base_s=self.settings.backoff_base_s, now=now)
            if row.status == MediaJobStatus.failed:
                self.metrics.jobs_given_up += 1
                log.error("job %s gave up after %d attempts: %s", row.job_key, row.attempts, exc)
            return

        asset = await store.store_asset(
            db, persona, job, image_bytes, self.settings.media_root,
            kind=_kind_for_job(job.job_key))
        _augment_keyframe_meta(asset, job.job_key)
        await queue_ops.mark_done(db, row, asset.id)
        self.metrics.jobs_done += 1
        self.metrics.gen_seconds.append(time.monotonic() - t0)

    # -- scheduling helpers --

    async def should_run(
        self, sessionmaker: async_sessionmaker[AsyncSession], now: datetime | None = None
    ) -> bool:
        """Window gate: run only when some active persona is in her sleep window AND work exists
        (FR-008-11 — never during awake/serving hours)."""
        now = now or datetime.now(timezone.utc)
        async with sessionmaker() as db:
            personas = (await db.execute(select(Persona))).scalars().all()
            if not any(
                in_media_window(now, p.timezone, self.settings) for p in personas
            ):
                return False
            return await queue_ops.pending_count(db) > 0


def _kind_for_job(job_key: str):
    """F-015 keyframe jobs (`<base>-first`/`<base>-last` keys) persist as kind=video_keyframe;
    everything else is a photo. Keeps the engine generic while the linked pair stays queryable."""
    from services.bot.models import MediaKind
    from services.imagegen import keyframes
    try:
        keyframes.split_keyframe_key(job_key)
        return MediaKind.video_keyframe
    except ValueError:
        return MediaKind.photo


def _augment_keyframe_meta(asset, job_key: str) -> None:
    """Stamp the pair linkage (`pair_id` + `frame`) into meta_json for keyframe assets (F-015
    FR-015-04) so `load_keyframe_pair` finds both halves."""
    import json as _json

    from services.imagegen import keyframes
    try:
        pair_id, frame = keyframes.split_keyframe_key(job_key)
    except ValueError:
        return
    meta = _json.loads(asset.meta_json or "{}")
    meta["pair_id"], meta["frame"] = pair_id, frame
    asset.meta_json = _json.dumps(meta, ensure_ascii=False)


async def check_empty_archive_alert(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> list[int]:
    """§6.4 alert: personas with an empty archive (NFR-008-03). Returns ids and logs the alert."""
    async with sessionmaker() as db:
        empty = await store.empty_archive_personas(db)
    if empty:
        log.error("ALERT empty media archive for persona ids: %s", empty)
    return empty
