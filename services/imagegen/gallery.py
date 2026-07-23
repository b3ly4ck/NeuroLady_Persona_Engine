"""Gallery-card photo provisioning (F-013 FR-013-12 / F-001 FR-001-25, ISS-002).

The S2 gallery card is the product's first impression and its conversion point, yet
`PERSONA.gallery_photo_ref` pointed at a file provisioning never created — so every card rendered
text-only via the (correct, but never-meant-to-be-normal) degrade path.

The nightly batch already produces a per-persona archive; this module **promotes one SFW frame from
it** to `media/<slug>/gallery/card.jpg` and points the persona at it. Pillow-only, no GPU.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import MediaAsset, MediaKind, Persona
from services.bot.personas_seed import persona_slug
from services.imagegen.store import parse_meta

log = logging.getLogger(__name__)

# Prefer a neutral, face-clear moment for the card (FR-013-12); these are matched against the
# asset's slot metadata, best first. Anything else is still usable as a last resort.
PREFERRED_POSES = ("close selfie", "medium waist-up", "companion shot", "candid moment")


def gallery_ref(persona_slug_value: str) -> str:
    """Canonical storage_ref for a persona's gallery card photo (§6.3)."""
    return f"media/{persona_slug_value}/gallery/card.jpg"


@dataclass
class GalleryCheck:
    """One persona's gallery-photo health (F-001 FR-001-25 operator-visible check)."""

    persona: str
    ref: str | None
    exists: bool

    @property
    def ok(self) -> bool:
        return bool(self.ref) and self.exists


def _candidates(assets: list[MediaAsset]) -> list[MediaAsset]:
    """SFW assets only (never an intimate one on the gallery card — FR-013-12), newest first,
    ordered by how well the pose suits a card."""
    sfw = [a for a in assets if not a.intimate and a.kind == MediaKind.photo]

    def rank(a: MediaAsset) -> tuple[int, str]:
        pose = (parse_meta(a).get("pose") or "").lower()
        for i, preferred in enumerate(PREFERRED_POSES):
            if preferred in pose:
                return (i, a.id)
        return (len(PREFERRED_POSES), a.id)

    return sorted(sfw, key=rank, reverse=False)


async def provision_gallery_photo(
    db: AsyncSession, persona: Persona, media_root: str | Path
) -> str | None:
    """Promote a suitable archive frame to this persona's gallery card (FR-013-12).

    Returns the new `gallery_photo_ref`, or None when she has no usable SFW asset yet (the card then
    keeps its documented text-only runtime fallback, F-001 FR-001-26).
    """
    assets = (
        await db.execute(select(MediaAsset).where(MediaAsset.persona_id == persona.id))
    ).scalars().all()
    picks = _candidates(list(assets))
    if not picks:
        log.warning("no SFW archive asset to source a gallery photo for %s", persona.name)
        return None

    root = Path(media_root)
    slug = persona_slug(persona.name)
    for asset in picks:
        src = root / asset.storage_ref.removeprefix("media/")
        if not src.exists():
            continue
        dst = root / slug / "gallery" / "card.jpg"
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image

            Image.open(src).convert("RGB").save(dst, quality=92)
        except Exception:  # noqa: BLE001 — fall back to a straight copy if Pillow is unhappy
            shutil.copy2(src, dst)
        persona.gallery_photo_ref = gallery_ref(slug)
        await db.flush()
        log.info("gallery photo for %s ← %s", persona.name, asset.id)
        return persona.gallery_photo_ref

    log.warning("archive rows exist for %s but no file resolved", persona.name)
    return None


async def check_gallery_photos(
    db: AsyncSession, media_root: str | Path
) -> list[GalleryCheck]:
    """Operator-visible health check (F-001 FR-001-25): which personas would render a text-only
    card. A missing gallery photo must be *flagged*, never silently accepted."""
    root = Path(media_root)
    out: list[GalleryCheck] = []
    for persona in (await db.execute(select(Persona))).scalars().all():
        ref = persona.gallery_photo_ref
        exists = bool(ref) and (root / str(ref).removeprefix("media/")).exists()
        check = GalleryCheck(persona=persona.name, ref=ref, exists=exists)
        if not check.ok:
            log.warning("gallery photo MISSING for %s (ref=%s)", persona.name, ref)
        out.append(check)
    return out
