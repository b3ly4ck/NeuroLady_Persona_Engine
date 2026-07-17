"""Job-queue operations over MEDIA_JOB (FR-008-11..14).

Durable DB-backed queue: F-011 (batch planner) enqueues; the night runner consumes. Idempotency
is the `job_key` unique constraint (enqueue twice → one row; process twice → one asset). Claiming
flips pending→running with a guarded UPDATE so two workers can't win the same job
(TC-FR-008-12-03). `running` rows older than the staleness cutoff are requeued — a crashed batch
resumes instead of losing jobs (FR-008-14).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import MediaJob, MediaJobStatus
from services.imagegen.contract import GenerationJob


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes — normalize to UTC before arithmetic."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def enqueue(db: AsyncSession, persona_id: int, job: GenerationJob) -> MediaJob:
    """Idempotent enqueue: an existing row with the same job_key is returned, not duplicated."""
    job.validate()
    existing = await db.scalar(select(MediaJob).where(MediaJob.job_key == job.job_key))
    if existing is not None:
        return existing
    row = MediaJob(
        job_key=job.job_key,
        persona_id=persona_id,
        payload_json=job.to_json(),
        status=MediaJobStatus.pending,
    )
    db.add(row)
    await db.flush()
    return row


async def claim_next(db: AsyncSession, now: datetime | None = None) -> MediaJob | None:
    """Claim one due pending job (pending → running) with a guarded UPDATE — under concurrency
    exactly one claimer wins a given job (TC-FR-008-12-03)."""
    now = now or _utcnow()
    candidates = (
        await db.execute(
            select(MediaJob)
            .where(MediaJob.status == MediaJobStatus.pending)
            .order_by(MediaJob.id)
        )
    ).scalars().all()
    for row in candidates:
        due = _aware(row.next_attempt_at)
        if due is not None and due > now:
            continue
        won = await db.execute(
            update(MediaJob)
            .where(MediaJob.id == row.id, MediaJob.status == MediaJobStatus.pending)
            .values(status=MediaJobStatus.running, claimed_at=now)
        )
        if won.rowcount == 1:
            await db.flush()
            await db.refresh(row)
            return row
    return None


async def mark_done(db: AsyncSession, row: MediaJob, asset_id: str) -> None:
    row.status = MediaJobStatus.done
    row.asset_id = asset_id
    row.error = ""
    await db.flush()


async def mark_failed_attempt(
    db: AsyncSession, row: MediaJob, error: str, *, max_attempts: int, backoff_base_s: float,
    now: datetime | None = None,
) -> None:
    """Retry with exponential backoff; on final give-up log + park as failed — the batch moves on
    and no partial file exists (FR-008-13; the store layer guarantees the file part)."""
    now = now or _utcnow()
    row.attempts += 1
    row.error = error[:2000]
    if row.attempts >= max_attempts:
        row.status = MediaJobStatus.failed
    else:
        row.status = MediaJobStatus.pending
        row.next_attempt_at = now + timedelta(seconds=backoff_base_s * (2 ** (row.attempts - 1)))
    await db.flush()


async def requeue_stale(
    db: AsyncSession, *, stale_after_s: float, now: datetime | None = None
) -> int:
    """Resume support: running jobs whose claim is older than the cutoff (crashed batch) go back
    to pending; completed jobs are naturally skipped because they are `done` (FR-008-14)."""
    now = now or _utcnow()
    cutoff = now - timedelta(seconds=stale_after_s)
    rows = (
        await db.execute(select(MediaJob).where(MediaJob.status == MediaJobStatus.running))
    ).scalars().all()
    n = 0
    for row in rows:
        claimed = _aware(row.claimed_at)
        if claimed is None or claimed <= cutoff:
            row.status = MediaJobStatus.pending
            row.claimed_at = None
            n += 1
    await db.flush()
    return n


async def pending_count(db: AsyncSession) -> int:
    rows = (
        await db.execute(select(MediaJob).where(MediaJob.status == MediaJobStatus.pending))
    ).scalars().all()
    return len(rows)
