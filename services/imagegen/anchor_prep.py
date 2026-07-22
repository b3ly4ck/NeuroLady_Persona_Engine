"""Reference-anchor preparation & validation (F-009 FR-009-15/16, architecture.md §4.3b).

The serving node rescales every anchor to ~384×384 for the vision encoder, so identity signal is
proportional to how much of the frame the subject occupies. Two authoring rules follow:

- the **face anchor** must be a tight head crop (the head fills the frame);
- the **body anchor** must be head-cropped (torso/figure, no face) so it carries anatomy only and
  cannot leak a second, competing face.

This module owns the deterministic image ops (crop) + lightweight validation the policy surfaces as
warnings. It has no model/GPU dependency — Pillow only — so it stays importable from the bot env.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class AnchorCheck:
    ok: bool
    reason: str = ""


def head_crop_body(src: str | Path, dst: str | Path, top_fraction: float = 0.22) -> Path:
    """Write a head-cropped copy of a full-figure body anchor (FR-009-16): drop the top
    `top_fraction` of the image (where the head sits) so the anchor carries anatomy only, no face.

    Deterministic, Pillow-only. Returns the destination path.
    """
    from PIL import Image

    top_fraction = min(max(top_fraction, 0.0), 0.6)
    img = Image.open(src).convert("RGB")
    w, h = img.size
    cropped = img.crop((0, int(h * top_fraction), w, h))
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(dst, quality=95)
    return dst


def tighten_face(src: str | Path, dst: str | Path, keep: float = 0.7) -> Path:
    """Write a tighter, centered square crop of a face anchor (FR-009-15) — keep the central
    `keep` fraction, which drops raised arms / background and enlarges the face's share of the
    ~384×384 the encoder sees. Deterministic, Pillow-only.
    """
    from PIL import Image

    keep = min(max(keep, 0.3), 1.0)
    img = Image.open(src).convert("RGB")
    w, h = img.size
    side = int(min(w, h) * keep)
    cx, cy = w // 2, int(h * 0.42)  # faces sit slightly above center in a selfie
    left = max(0, min(cx - side // 2, w - side))
    top = max(0, min(cy - side // 2, h - side))
    img.crop((left, top, left + side, top + side)).save(Path(dst), quality=95)
    return Path(dst)


def validate_body_anchor(path: str | Path, max_aspect: float = 1.6) -> AnchorCheck:
    """Advisory orientation check for a body anchor (FR-009-16): a torso/figure crop should be
    portrait (taller than wide). A landscape image is clearly not a usable body anchor.

    This is a WARNING signal (surfaced by the policy), NOT a hard gate and NOT face detection:
    verifying that no face is in-frame needs a real detector and lives in Persona Studio
    provisioning. The reliable head-removal mechanism is `head_crop_body`, applied at provisioning.
    """
    from PIL import Image

    w, h = Image.open(path).size
    if h <= 0:
        return AnchorCheck(False, "unreadable image")
    aspect = w / h
    if aspect > max_aspect:
        return AnchorCheck(False, f"body anchor aspect {aspect:.2f} is landscape — a body anchor "
                                  f"should be a portrait torso crop (FR-009-16)")
    return AnchorCheck(True)
