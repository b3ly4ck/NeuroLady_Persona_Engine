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

from services.bot.models import MediaAsset, MediaIdSequence, MediaKind, MediaSend, Persona
from services.imagegen.contract import GenerationJob

_TMP_SUFFIX = ".part"


def asset_relpath(persona_slug: str, med_id: str) -> str:
    """Relative storage_ref inside the media library (§6.3)."""
    return f"media/{persona_slug}/photos/{med_id}.png"


def _id_suffix(med_id: str) -> int:
    """The numeric tail of a MED-<slug>-<nnnnn> id; 0 for anything unparseable."""
    tail = (med_id or "").rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 0


async def allocate_med_id(db: AsyncSession, persona: Persona, persona_slug: str) -> str:
    """Next MED-<slug>-<nnnnn> for the persona, **monotonically** (F-021 FR-021-13 / D1).

    This used to be `count(*) + 1`, which is safe only while nothing is ever deleted. F-021 evicts
    frames, and a count-derived id rewinds the moment it does — the next photo would be born with a
    retired id, and `MediaSend` (keyed by that id, and deliberately outliving its asset) would treat
    a brand-new image as one the user had already seen. The counter here only ever moves forward.

    It is seeded from the highest suffix ever observed — across live assets *and* send history — so
    an existing archive migrates without reissuing anything. The PK uniqueness still backstops a
    race (the loser retries with the next number).
    """
    row = await db.get(MediaIdSequence, persona.id)
    highest = row.last_value if row is not None else 0
    # Seed/repair from reality: rows that predate the counter, and sends whose asset is already gone.
    for existing in (
        await db.execute(select(MediaAsset.id).where(MediaAsset.persona_id == persona.id))
    ).scalars().all():
        highest = max(highest, _id_suffix(existing))
    for sent in (
        await db.execute(
            select(MediaSend.asset_id).where(MediaSend.asset_id.like(f"MED-{persona_slug}-%"))
        )
    ).scalars().all():
        highest = max(highest, _id_suffix(sent))

    nxt = highest + 1
    if row is None:
        db.add(MediaIdSequence(persona_id=persona.id, last_value=nxt))
    else:
        row.last_value = nxt
    await db.flush()
    return f"MED-{persona_slug}-{nxt:05d}"


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


async def retained_assets(db: AsyncSession, persona_id: int) -> list[MediaAsset]:
    """The persona's WHOLE retained library, newest first (F-021 FR-021-01).

    Replaces `latest_available_assets` as what bounds candidacy: F-021 makes freshness a ranking
    signal, so age no longer filters. Bounded by the retention cap rather than by a day window, and
    index-backed on `(persona_id, created_at)` so the reply path stays cheap (NFR-021-04).
    `latest_available_assets` survives only as the F-008 NFR-008-03 "which day is current" helper.
    """
    rows = (
        await db.execute(
            select(MediaAsset)
            .where(MediaAsset.persona_id == persona_id)
            .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
        )
    ).scalars().all()
    return list(rows)


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
