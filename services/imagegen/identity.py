"""F-009 — Appearance & Identity Consistency: the reference-conditioning POLICY.

This module owns *which* persona reference(s) condition an image and *how strongly* — the
guarantee that every generated image is unmistakably the **same girl**. It does **not** run the
model or store the asset (that is the F-008 engine), author the scene/pose (F-010), gate intimacy
(F-014), or capture the reference photos (Persona Studio, §3.8/§4.4). It **consumes** each persona's
`face_ref` / `fullbody_ref` (architecture.md §5.1) and emits the chosen reference(s) into the fixed
F-008 job contract's `GenerationJob.references` field (FR-009-10 — model-agnostic, rides the job).

Design points mapped to requirements:
- **Reference per shot type** (FR-009-03): a face-focused shot conditions on the *face* anchor, a
  full-figure shot on the *full-body* anchor. Shot type is inferred from the job's slot/prompt
  metadata (authored by F-010) via config-driven keyword lists.
- **Config-driven** (FR-009-03 / NFR-009-07): selection keywords, the default shot type, per-shot
  conditioning strength, and the no-reference behaviour are all tunable via `IdentityPolicySettings`
  (env prefix `IDENTITY_`) — no code change to re-tune.
- **No-reference safe path** (FR-009-08): a persona without references NEVER yields a wrong-identity
  generation. The policy returns a *skipped* selection (leaving the job reference-less, which the
  F-008 backend rejects with a defined error) or a configured placeholder — a clear result type,
  never a crash and never someone else's face.
- **Strict per-persona isolation** (FR-009-07): the policy reads ONLY the persona object handed to
  it; one persona's references can never reach another's job.
- **Model-agnostic** (FR-009-10 / NFR-009-05): the only coupling to the engine is the `references`
  list on the fixed job contract — this module imports no model/server code at all.

The `strength` a selection carries is a policy-level decision (used for logging / future backends
that accept a conditioning weight); it does not need to ride the job contract, so identity
conditioning stays decoupled from any specific model's knobs.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict

from services.imagegen.contract import GenerationJob


class ShotType(str, enum.Enum):
    """Whether a shot is framed on the face or the whole figure (drives which anchor is primary)."""

    face = "face"
    full_body = "full_body"


class NoReferenceAction(str, enum.Enum):
    """What to do when a persona has no usable reference at all (FR-009-08)."""

    skip = "skip"              # produce a skipped selection → reference-less job (engine rejects)
    placeholder = "placeholder"  # condition on a config-defined placeholder reference


class NoReferenceError(RuntimeError):
    """A persona has no usable reference and strict conditioning was requested (FR-009-08).

    Raised only by `require` — the default `select`/`apply` path degrades safely to a *skipped*
    selection instead, so a caller never accidentally generates a wrong-identity image.
    """


class HasReferences(Protocol):
    """The only persona surface this policy touches: her two identity anchors (per-persona read)."""

    face_ref: str | None
    fullbody_ref: str | None


# ── canonical reference layout (architecture.md §6.3) ───────────────────────────────────────────

REFERENCE_SUBDIR = "reference"


def face_reference_path(persona_slug: str) -> str:
    """Conventional media path of a persona's face anchor (PERSONA.face_ref, §5.1/§6.3)."""
    return f"media/{persona_slug}/{REFERENCE_SUBDIR}/face.png"


def fullbody_reference_path(persona_slug: str) -> str:
    """Conventional media path of a persona's full-body anchor (PERSONA.fullbody_ref)."""
    return f"media/{persona_slug}/{REFERENCE_SUBDIR}/fullbody.png"


# ── configuration (FR-009-03 / NFR-009-07: tune selection + strength without code changes) ───────


class IdentityPolicySettings(BaseSettings):
    """Config for the identity-conditioning policy (env prefix ``IDENTITY_``).

    Everything that decides *which* reference conditions a shot and *how strongly* lives here, so
    the policy is re-tunable without a code change (NFR-009-07). Keyword lists classify a shot from
    its F-010-authored slot/prompt text; strengths are per shot type; the no-reference behaviour and
    optional placeholder cover the safe-degradation path (FR-009-08).
    """

    model_config = SettingsConfigDict(env_prefix="IDENTITY_", env_file=".env", extra="ignore")

    # Substrings (lowercased) that mark a shot as face-focused vs full-figure. Full-body wins ties.
    face_keywords: tuple[str, ...] = (
        "selfie", "portrait", "headshot", "head shot", "close-up", "closeup", "close up",
        "face", "profile pic", "headshot", "bust",
    )
    full_body_keywords: tuple[str, ...] = (
        "full body", "full-body", "fullbody", "full figure", "full-figure", "full length",
        "full-length", "head to toe", "head-to-toe", "whole body", "standing", "outfit of the day",
        "ootd", "posing",
    )
    # When neither keyword set matches, assume this shot type (most content is selfies → face).
    default_shot_type: ShotType = ShotType.face
    # Per-shot conditioning strength (policy-level; forwarded to backends that accept a weight).
    face_strength: float = 0.9
    full_body_strength: float = 0.85
    # Attach the *other* anchor as a secondary reference (extra identity signal) when available.
    # FR-009-11: the body anchor carries anatomy a face crop cannot — always send it when it exists.
    include_secondary_reference: bool = True
    # Model input limit — TextEncodeQwenImageEditPlus binds image1..image3 (architecture.md §4.3b).
    max_references: int = 3
    # No-reference behaviour (FR-009-08). With "placeholder", `placeholder_reference` is used.
    no_reference_action: NoReferenceAction = NoReferenceAction.skip
    placeholder_reference: str = ""


@lru_cache
def get_identity_settings() -> IdentityPolicySettings:
    return IdentityPolicySettings()


# ── the identity-preservation directive (FR-009-12/13, architecture.md §4.3b) ────────────────────
#
# This is the single most important sentence in the whole image pipeline. The serving node injects
# the anchors as "Picture 1: <img> Picture 2: <img>" ahead of our text, so the prompt MUST open by
# binding the output to those pictures. Without it the model reads a generic subject ("a woman")
# and drifts off the reference — the photo stops being *her*.
#
# It PRESERVES, it never DESCRIBES: no hair/eye colour, no body type — the pictures carry that
# (FR-009-13), which is also why F-010's banned-appearance-vocabulary guard must exempt this text.

_DIRECTIVE_ONE = (
    "Preserve the exact face, facial features, head shape, skin tone and body proportions of the "
    "person in Picture 1. This is the same person — do not change her identity or anatomy. "
    "Place this same person in the following scene: "
)
_DIRECTIVE_TWO = (
    "Preserve the exact face and facial features of the person in Picture 1, and the exact body "
    "proportions and anatomy of the same person in Picture 2. Both pictures show the same person — "
    "do not change her identity or anatomy. Place this same person in the following scene: "
)


def preservation_directive(reference_count: int) -> str:
    """The mandatory opening of every generation prompt (FR-009-12; F-010 FR-010-12 places it).

    Wording depends on how many anchors are bound, because the node numbers them Picture 1..N:
    one anchor → everything is preserved from Picture 1; two → face from Picture 1, anatomy from
    Picture 2. Returns "" for zero references (nothing to bind to — the no-reference safe path).
    """
    if reference_count <= 0:
        return ""
    return _DIRECTIVE_ONE if reference_count == 1 else _DIRECTIVE_TWO


# ── selection result (a clear result type — never a silent wrong-identity, FR-009-08) ────────────


@dataclass
class IdentitySelection:
    """The policy's decision for one job: which reference(s), ordered, and at what strength.

    ``references`` is exactly what should land on ``GenerationJob.references`` (primary anchor
    first, since the F-008 backend stages ``references[0]``). ``skipped`` marks the no-reference
    safe path: an empty reference list the engine will reject rather than generate a wrong face.
    """

    references: list[str] = field(default_factory=list)
    strength: float = 0.0
    shot_type: ShotType = ShotType.face
    skipped: bool = False
    reason: str = ""

    @property
    def primary(self) -> str | None:
        return self.references[0] if self.references else None


# ── the policy ───────────────────────────────────────────────────────────────────────────────────


class IdentityPolicy:
    """Selects and applies identity conditioning for one generation job (F-009)."""

    def __init__(self, settings: IdentityPolicySettings | None = None) -> None:
        self.settings = settings or get_identity_settings()

    # -- shot classification (from F-010-authored slot/prompt metadata) --

    def classify_shot(self, job: GenerationJob) -> ShotType:
        """Infer face-vs-full-body from the job's prompt + slot text (config-driven keywords).

        Full-body keywords take precedence (a "full body selfie" is a full-figure shot); if nothing
        matches, the configured default is used.
        """
        haystack = " ".join(
            t for t in (
                job.prompt,
                job.slot.pose, job.slot.activity, job.slot.background,
                job.slot.location, job.slot.time_of_day,
            ) if t
        ).lower()
        s = self.settings
        if any(kw in haystack for kw in s.full_body_keywords):
            return ShotType.full_body
        if any(kw in haystack for kw in s.face_keywords):
            return ShotType.face
        return s.default_shot_type

    # -- selection (pure; reads ONLY this persona's anchors — per-persona isolation, FR-009-07) --

    def select(self, persona: HasReferences, job: GenerationJob) -> IdentitySelection:
        """Choose the reference(s) for `job` using only `persona`'s own anchors.

        Face-focused shots lead with the face anchor; full-figure shots lead with the full-body
        anchor (falling back to the face anchor when no full-body one exists — still the right
        identity). With no usable anchor at all, returns a *skipped* selection (or a placeholder
        per config) — never another persona's reference, never a crash.
        """
        s = self.settings
        shot = self.classify_shot(job)
        face = (persona.face_ref or "").strip() or None
        body = (persona.fullbody_ref or "").strip() or None

        if face is None and body is None:
            return self._no_reference(shot)

        if shot is ShotType.full_body:
            primary, secondary = (body or face), (face if body else None)
            strength = s.full_body_strength
        else:
            primary, secondary = (face or body), (body if face else None)
            strength = s.face_strength

        refs = [primary]
        if s.include_secondary_reference and secondary and secondary != primary:
            refs.append(secondary)
        refs = refs[: max(1, s.max_references)]  # model binds at most N pictures (FR-009-11)
        return IdentitySelection(
            references=refs, strength=strength, shot_type=shot,
            reason=f"{shot.value} shot conditioned on {len(refs)} reference(s)",
        )

    def _no_reference(self, shot: ShotType) -> IdentitySelection:
        s = self.settings
        if s.no_reference_action is NoReferenceAction.placeholder and s.placeholder_reference.strip():
            return IdentitySelection(
                references=[s.placeholder_reference.strip()], strength=0.0, shot_type=shot,
                skipped=False, reason="no persona reference — using configured placeholder",
            )
        return IdentitySelection(
            references=[], strength=0.0, shot_type=shot, skipped=True,
            reason="no persona reference — generation skipped (never a wrong-identity image)",
        )

    # -- application onto the fixed F-008 job contract (FR-009-02 / FR-009-10) --

    def apply(self, persona: HasReferences, job: GenerationJob) -> IdentitySelection:
        """Write the selected reference(s) onto `job.references` and return the decision.

        This is the single integration point with F-008: the policy only ever touches the job's
        `references` field (the fixed, model-agnostic contract). A skipped selection leaves the job
        reference-less, so the engine's backend rejects it with a defined error rather than emitting
        a wrong-identity image.
        """
        selection = self.select(persona, job)
        job.references = list(selection.references)
        return selection

    def require(self, persona: HasReferences, job: GenerationJob) -> IdentitySelection:
        """Like `apply`, but raise `NoReferenceError` when the persona has no usable reference.

        For callers that want a hard stop instead of a silent skip. Either way, a wrong-identity
        image is never produced.
        """
        selection = self.apply(persona, job)
        if selection.skipped:
            raise NoReferenceError(selection.reason)
        return selection
