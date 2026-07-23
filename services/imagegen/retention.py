"""F-021 — media archive retention: what stays on disk and what delivery may draw from.

The archive used to grow forever while delivery could only see one day (F-012 `select_asset`, now
widened via `store.retained_assets`). This module owns the other half: a **count-based per-persona
cap** with an eviction order that protects unconsumed GPU work.

The economics decide every rule here. A frame costs **~155 s of GPU** and **~1.4 MB of disk**;
storage is nearly free, generation is not. Hence:

* evict on a **size cap**, never on age (FR-021-04) — an old frame nobody has seen is still an asset;
* evict **already-sent frames first, oldest first**, and only then un-sent ones (FR-021-05) — an
  un-sent frame is GPU time nobody has consumed yet;
* several protections **outrank the cap** rather than the other way round; when they collide with it
  the cap is left exceeded and reported (FR-021-12) instead of destroying something valuable:

    1. **floor** — never below the configured minimum, never an empty archive (FR-021-06, D4);
    2. **grace** — frames younger than `grace_hours` are untouchable (D5), so a too-small cap cannot
       delete the batch that was just paid for;
    3. **context recency** — an asset sent within F-012's `context_recency_hours` is untouchable
       (FR-021-15, D3), because `recent_sends` inner-joins `MediaSend ⋈ MediaAsset`: evicting it
       would silently drop the photo from her conversation context and reopen ISS-006 (she invents a
       background for a photo she just sent).

Eviction is atomic per victim — the file is staged aside, the row dropped in a SAVEPOINT, and only
then is the file unlinked — so a failure on either side leaves **no orphan of either kind**
(FR-021-07 / NFR-021-07). Runs off the reply hot path, after the F-011 night batch (FR-021-08 / D8).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import MediaAsset, MediaSend, Persona

log = logging.getLogger(__name__)

# Staged-for-deletion marker: not a *.png, so `reconcile()` never counts it as an orphan file.
_EVICTING_SUFFIX = ".evicting"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; comparisons here are always UTC-aware."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RetentionConfig:
    """Every retention knob — tunable without a code change (NFR-021-06, architecture.md §4.8).

    `cap` is a count, not bytes: it is the number of frames a persona keeps. `per_persona_cap`
    overrides it by persona id for personas that deserve a bigger or smaller library.
    """

    cap: int = 60
    floor: int = 6
    # D5: nothing younger than this may be evicted, whatever the cap says.
    grace_hours: float = 24.0
    # D3 / FR-021-15: mirrors F-012's `context_recency_hours` — assets sent inside her memory window.
    context_recency_hours: float = 48.0
    per_persona_cap: dict[int, int] = field(default_factory=dict)

    def cap_for(self, persona_id: int) -> int:
        """The effective cap for one persona: the override if present, else the global cap."""
        return self.per_persona_cap.get(persona_id, self.cap)


DEFAULT_CONFIG = RetentionConfig()


def sanitize(cfg: RetentionConfig) -> tuple[RetentionConfig, list[str]]:
    """Coerce a broken config to documented defaults (NFR-021-06).

    A misconfiguration must never mean "delete everything": non-numeric or negative values fall back
    to the defaults, and the degradation is returned for the report rather than swallowed.
    """
    notes: list[str] = []
    d = DEFAULT_CONFIG

    def _num(value, default, name: str) -> float:
        try:
            n = float(value)
        except (TypeError, ValueError):
            notes.append(f"config: {name}={value!r} is not numeric — using {default}")
            return float(default)
        if n < 0:
            notes.append(f"config: {name}={value!r} is negative — using {default}")
            return float(default)
        return n

    cap = int(_num(cfg.cap, d.cap, "cap"))
    floor = int(_num(cfg.floor, d.floor, "floor"))
    grace = _num(cfg.grace_hours, d.grace_hours, "grace_hours")
    recency = _num(cfg.context_recency_hours, d.context_recency_hours, "context_recency_hours")
    clean = RetentionConfig(
        cap=cap, floor=floor, grace_hours=grace, context_recency_hours=recency,
        per_persona_cap=dict(cfg.per_persona_cap or {}),
    )
    return clean, notes


@dataclass
class RetentionReport:
    """What one persona's run did — the §6.4 metrics (FR-021-12).

    A no-op run still produces one: "nothing happened" must be an explicit signal, not silence.
    `evicted_unsent` is called out separately so the operator can see that un-sent GPU work had to
    be destroyed (US-021-04-02) and raise the cap.
    """

    persona_id: int
    kept: int = 0
    evicted: int = 0
    evicted_sent: int = 0
    evicted_unsent: int = 0
    archive_size: int = 0
    cap: int = 0
    cap_exceeded: bool = False
    repaired: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "persona_id": self.persona_id, "kept": self.kept, "evicted": self.evicted,
            "evicted_sent": self.evicted_sent, "evicted_unsent": self.evicted_unsent,
            "archive_size": self.archive_size, "cap": self.cap,
            "cap_exceeded": self.cap_exceeded, "repaired": list(self.repaired),
            "failures": list(self.failures), "notes": list(self.notes),
        }


def _asset_path(media_root: str | Path, asset: MediaAsset) -> Path:
    return Path(media_root) / asset.storage_ref.removeprefix("media/")


async def _sent_asset_ids(db: AsyncSession, persona_id: int) -> set[str]:
    """Ids this persona's frames have been delivered under, **to any user** (D6).

    A frame consumed by one user is weaker GPU work to destroy than one nobody has seen; per-user
    no-repeat is unaffected because it reads `MediaSend` directly, not the asset's presence.
    """
    rows = (await db.execute(select(MediaSend.asset_id))).scalars().all()
    return set(rows)


async def _recently_sent_ids(db: AsyncSession, cutoff: datetime) -> set[str]:
    """Ids sent within the context-recency window — untouchable (FR-021-15 / D3)."""
    rows = (
        await db.execute(select(MediaSend.asset_id).where(MediaSend.sent_at >= cutoff))
    ).scalars().all()
    return set(rows)


async def _evict_one(
    db: AsyncSession, asset: MediaAsset, media_root: str | Path, report: RetentionReport
) -> bool:
    """Remove one frame's file and row **together** — no orphan of either kind (FR-021-07).

    Two-phase, because a filesystem is not transactional and the two failure modes pull in opposite
    directions (TC-FR-021-07-02 wants the row kept when the file survives; TC-FR-021-07-03 wants the
    file kept when the row survives):

      1. **rename** the file aside — atomic and reversible. If this fails, nothing has changed and
         the row stays;
      2. delete the row inside a **SAVEPOINT**. If that raises, the savepoint rolls back *and* the
         file is renamed back, so the pair is intact;
      3. only then unlink the renamed file.

    A crash between 2 and 3 leaves a `.evicting` leftover with no row — invisible to `reconcile()`
    (it globs `*.png`) and swept by the next run. Crucially the outer transaction is never rolled
    back: a failure on one victim must not undo the evictions already done in this run.
    """
    path = _asset_path(media_root, asset)
    asset_id = asset.id
    staged: Path | None = None
    if path.exists():
        staged = path.with_name(path.name + _EVICTING_SUFFIX)
        try:
            os.replace(path, staged)
        except OSError as exc:
            report.failures.append(f"{asset_id}: file delete failed ({exc})")
            log.warning("retention: could not stage %s for deletion: %s", path, exc)
            return False

    try:
        async with db.begin_nested():
            await db.delete(asset)
    except Exception as exc:  # savepoint rolled back — put the file back where it belongs
        if staged is not None:
            try:
                os.replace(staged, path)
            except OSError:  # pragma: no cover - the file is gone either way, report it
                report.failures.append(f"{asset_id}: file could not be restored after row failure")
        report.failures.append(f"{asset_id}: row delete failed ({exc})")
        log.warning("retention: could not delete row %s: %s", asset_id, exc)
        return False

    if staged is not None:
        try:
            os.unlink(staged)
        except OSError as exc:  # pragma: no cover - row is gone; the leftover is swept next run
            log.warning("retention: staged file %s left behind: %s", staged, exc)
    return True


def _sweep_staged(media_root: str | Path, report: RetentionReport) -> None:
    """Delete `.evicting` leftovers from a run that died mid-eviction (NFR-021-07-03)."""
    for leftover in Path(media_root).glob(f"*/photos/*{_EVICTING_SUFFIX}"):
        try:
            os.unlink(leftover)
            report.repaired.append(leftover.name)
        except OSError:  # pragma: no cover
            log.warning("retention: could not sweep %s", leftover)


async def _repair_orphan_rows(
    db: AsyncSession, assets: list[MediaAsset], media_root: str | Path, report: RetentionReport
) -> list[MediaAsset]:
    """Drop rows whose file is already gone — an interrupted previous run (NFR-021-07-03).

    **Guarded on purpose:** if *every* row is missing its file, that is far more likely an unmounted
    or misconfigured media root than a batch of interrupted evictions, and wiping the archive would
    be the worst possible response. In that case nothing is repaired and the anomaly is reported.
    """
    missing = [a for a in assets if not _asset_path(media_root, a).exists()]
    if not missing:
        return assets
    if len(missing) == len(assets):
        report.notes.append(
            f"every one of {len(assets)} rows is missing its file — media root looks wrong, "
            "skipping repair"
        )
        return assets
    for asset in missing:
        await db.delete(asset)
        report.repaired.append(asset.id)
    await db.flush()
    return [a for a in assets if a not in missing]


async def run_retention(
    db: AsyncSession,
    persona_id: int,
    media_root: str | Path,
    cfg: RetentionConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> RetentionReport:
    """Bring one persona's archive back to her cap, cheapest frames first (FR-021-04/05/06/07).

    Protections outrank the cap: floor > grace > context-recency. When they make the cap
    unreachable the run reports `cap_exceeded=True` rather than deleting something it must not.
    Idempotent — a second run immediately after evicts nothing.
    """
    now = now or _utcnow()
    cfg, notes = sanitize(cfg)
    cap = cfg.cap_for(persona_id)
    report = RetentionReport(persona_id=persona_id, cap=cap, notes=list(notes))

    assets = list(
        (
            await db.execute(
                select(MediaAsset)
                .where(MediaAsset.persona_id == persona_id)
                .order_by(MediaAsset.created_at.asc(), MediaAsset.id.asc())
            )
        ).scalars().all()
    )
    _sweep_staged(media_root, report)
    assets = await _repair_orphan_rows(db, assets, media_root, report)

    # D4: a floor above the cap is a contradiction; the floor wins — never a crippled archive.
    floor = cfg.floor
    if floor > cap:
        report.notes.append(f"floor={floor} exceeds cap={cap} — floor wins, cap unsatisfiable")
    # NFR-021-05: at least one frame always survives, under EVERY config including cap=floor=0.
    effective_floor = max(1, floor)

    target = max(cap, effective_floor)
    over = len(assets) - target
    if over <= 0:
        report.kept = report.archive_size = len(assets)
        _log_report(report)
        return report

    grace_cutoff = now - timedelta(hours=cfg.grace_hours)
    recency_cutoff = now - timedelta(hours=cfg.context_recency_hours)
    protected_recent = await _recently_sent_ids(db, recency_cutoff)
    sent_ever = await _sent_asset_ids(db, persona_id)

    def _protected(asset: MediaAsset) -> str | None:
        created = _aware(asset.created_at) or now
        if created > grace_cutoff:
            return "grace"
        if asset.id in protected_recent:
            return "context-recency"
        return None

    # FR-021-05: already-sent first, then un-sent — oldest first within each tier. `assets` is
    # already oldest-first, so the tiers keep that order. Intimacy is irrelevant here (FR-021-09-04).
    evictable = [(a, _protected(a)) for a in assets]
    victims_sent = [a for a, prot in evictable if prot is None and a.id in sent_ever]
    victims_unsent = [a for a, prot in evictable if prot is None and a.id not in sent_ever]
    protected_count = sum(1 for _, prot in evictable if prot is not None)

    ordered = victims_sent + victims_unsent
    removed = 0
    for asset in ordered:
        if removed >= over:
            break
        was_sent = asset.id in sent_ever
        if await _evict_one(db, asset, media_root, report):
            removed += 1
            report.evicted += 1
            if was_sent:
                report.evicted_sent += 1
            else:
                report.evicted_unsent += 1
    await db.flush()

    report.kept = report.archive_size = len(assets) - report.evicted
    if report.archive_size > cap:
        report.cap_exceeded = True
        why = []
        if protected_count:
            why.append(f"{protected_count} protected (grace/context-recency)")
        if floor > cap:
            why.append(f"floor={floor}")
        if report.failures:
            why.append(f"{len(report.failures)} deletion failures")
        report.notes.append(
            f"cap={cap} left exceeded at {report.archive_size}" + (f" — {', '.join(why)}" if why else "")
        )
    _log_report(report)
    return report


def _log_report(report: RetentionReport) -> None:
    """§6.4 observability — every run says what it did, including the no-op ones (FR-021-12)."""
    log.info(
        "retention persona=%s kept=%s evicted=%s (sent=%s unsent=%s) size=%s cap=%s%s%s%s",
        report.persona_id, report.kept, report.evicted, report.evicted_sent,
        report.evicted_unsent, report.archive_size, report.cap,
        " CAP-EXCEEDED" if report.cap_exceeded else "",
        f" repaired={len(report.repaired)}" if report.repaired else "",
        f" failures={report.failures}" if report.failures else "",
    )


async def run_retention_all(
    db: AsyncSession,
    media_root: str | Path,
    cfg: RetentionConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> list[RetentionReport]:
    """Retention across the whole roster (FR-021-10).

    Per-persona isolation is total: one persona's cap, floor and eviction touch nothing else, and a
    failure on one persona never stops the others (mirrors F-011 NFR-011-07).
    """
    persona_ids = (await db.execute(select(Persona.id))).scalars().all()
    reports: list[RetentionReport] = []
    for pid in persona_ids:
        try:
            reports.append(await run_retention(db, pid, media_root, cfg, now))
        except Exception as exc:  # one persona's failure must not cost the rest their run
            log.exception("retention failed for persona %s", pid)
            reports.append(
                RetentionReport(persona_id=pid, failures=[f"run failed: {exc}"])
            )
    return reports
