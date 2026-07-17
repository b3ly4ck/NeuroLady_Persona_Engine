"""Asset storage: atomic file write + MEDIA_ASSET row, 1:1 by MED-id (FR-008-07..09).

Order is sacred: bytes → temp file → fsync → atomic rename → ONLY THEN the DB row. A crash at any
point leaves either nothing or a complete file; never a half-file posing as an asset
(TC-FR-008-09-*), never a row without a durable file (NFR-008-05).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import MediaAsset, MediaKind, Persona
from services.imagegen.contract import GenerationJob

_TMP_SUFFIX = ".part"


def asset_relpath(persona_slug: str, med_id: str) -> str:
    """Relative storage_ref inside the media library (§6.3)."""
    return f"media/{persona_slug}/photos/{med_id}.png"


async def allocate_med_id(db: AsyncSession, persona: Persona, persona_slug: str) -> str:
    """Next MED-<slug>-<nnnnn> for the persona (scheme §5.1). Sequential per persona; the PK
    uniqueness backstops any race (the loser retries with the next number)."""
    count = await db.scalar(
        select(func.count()).select_from(MediaAsset).where(MediaAsset.persona_id == persona.id)
    )
    return f"MED-{persona_slug}-{(count or 0) + 1:05d}"


def atomic_write(target: Path, data: bytes) -> None:
    """Temp-then-rename with fsync — the partial is invisible to archive scans (FR-008-09)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + _TMP_SUFFIX)
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)


async def store_asset(
    db: AsyncSession,
    persona: Persona,
    job: GenerationJob,
    image_bytes: bytes,
    media_root: str | Path,
    kind: MediaKind = MediaKind.photo,
) -> MediaAsset:
    """Persist one finished generation: file first (atomic), row second (FR-008-07/08/09)."""
    med_id = await allocate_med_id(db, persona, job.persona_slug)
    relpath = asset_relpath(job.persona_slug, med_id)
    # media_root IS the media/ dir; storage_ref carries the media/ prefix for §6.3 portability.
    target = Path(media_root) / job.persona_slug / "photos" / f"{med_id}.png"
    atomic_write(target, image_bytes)

    asset = MediaAsset(
        id=med_id,
        persona_id=persona.id,
        kind=kind,
        intimate=job.intimate,
        intimacy_level=job.intimacy_level,
        storage_ref=relpath,
        meta_json=job.slot_meta_json(),
    )
    db.add(asset)
    await db.flush()
    return asset


# ── archive integrity & degrade helpers (NFR-008-03/05) ─────────────────────────────────────────


async def reconcile(db: AsyncSession, media_root: str | Path) -> dict[str, list[str]]:
    """1:1 check: every row has its file, every archived file its row (TC-NFR-008-05-*)."""
    rows = (await db.execute(select(MediaAsset))).scalars().all()
    root = Path(media_root)
    rows_missing_file = [
        a.id for a in rows
        if not (root / a.storage_ref.removeprefix("media/")).exists()
    ]
    known_ids = {a.id for a in rows}
    files_missing_row = [
        str(p) for p in root.glob("*/photos/*.png") if p.stem not in known_ids
    ]
    return {"rows_missing_file": rows_missing_file, "files_missing_row": files_missing_row}


async def assets_for_day(
    db: AsyncSession, persona_id: int, day: datetime
) -> list[MediaAsset]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(hour=23, minute=59, second=59)
    rows = (
        await db.execute(
            select(MediaAsset).where(
                MediaAsset.persona_id == persona_id,
                MediaAsset.created_at >= start,
                MediaAsset.created_at <= end,
            )
        )
    ).scalars().all()
    return list(rows)


async def latest_available_assets(
    db: AsyncSession, persona_id: int, now: datetime | None = None
) -> list[MediaAsset]:
    """Today's archive, else the most recent prior day's — never nothing while any assets exist
    (NFR-008-03 degrade: a failed batch falls back to yesterday's archive)."""
    now = now or datetime.now(timezone.utc)
    today = await assets_for_day(db, persona_id, now)
    if today:
        return today
    latest = await db.scalar(
        select(func.max(MediaAsset.created_at)).where(MediaAsset.persona_id == persona_id)
    )
    if latest is None:
        return []
    if latest.tzinfo is None:  # SQLite returns naive datetimes
        latest = latest.replace(tzinfo=timezone.utc)
    return await assets_for_day(db, persona_id, latest)


async def empty_archive_personas(db: AsyncSession, now: datetime | None = None) -> list[int]:
    """Persona ids with NO assets at all — the §6.4 empty-archive alert condition."""
    persona_ids = (await db.execute(select(Persona.id))).scalars().all()
    out: list[int] = []
    for pid in persona_ids:
        have = await db.scalar(
            select(func.count()).select_from(MediaAsset).where(MediaAsset.persona_id == pid)
        )
        if not have:
            out.append(pid)
    return out


def parse_meta(asset: MediaAsset) -> dict:
    try:
        return json.loads(asset.meta_json or "{}")
    except json.JSONDecodeError:
        return {}
