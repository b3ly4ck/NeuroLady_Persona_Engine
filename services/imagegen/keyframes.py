"""F-015 — Intimate Video Keyframes: author + queue + store a gated first/last frame PAIR.

F-015 owns **authoring and producing the keyframe pair** (start frame → end frame) for a short
intimate clip. It is deliberately *keyframe-ready and video-model-agnostic*: **video synthesis is
out of scope** (the image-to-video model — Wan 2.2 / HunyuanVideo-Avatar — is deferred,
architecture.md §4.3/§3.9). This module produces and stores the pair and stops there; a future
i2v runner consumes the stored pair with no schema/redesign change (FR-015-07/08, NFR-015-06).

It is strictly **additive** over the F-008 engine — it does not modify the engine's files:
- the **intimacy gate is F-014's** (age/consent, relationship stage, hard safety boundary, ceiling
  clamp). F-015 REQUIRES it as an injected dependency and routes every request through it FIRST;
  it adds **no looser path** for video (FR-015-01, NFR-015-01).
- pairs are **generated via F-008** (the fixed job contract) with **F-009 identity** conditioning
  (FR-015-03), **queued** through `queue_ops`, never inline (FR-015-05, NFR-015-04).
- storage reuses `store.store_asset(kind=video_keyframe)` and augments `meta_json` with the
  `{pair_id, frame}` pairing (FR-015-04) — no engine file is touched.

This module contains **no generation call and no video dependency** (FR-015-08): it builds jobs,
gates, enqueues, and stores handed-in bytes. Generation itself is the night runner's job (F-008).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.models import MediaAsset, MediaKind, Persona
from services.imagegen import queue_ops, store
from services.imagegen.contract import GenerationJob, GenParams, SlotMeta

# Linked-key convention: one logical pair → two jobs `<base>-first` / `<base>-last`. The pair id is
# the base key; the frame role is recoverable from the suffix (FR-015-04 pairing).
FIRST_SUFFIX = "-first"
LAST_SUFFIX = "-last"


# ── F-014 intimacy gate contract (REUSED, never owned here) ───────────────────────────────────────
#
# F-014 owns the gate; F-015 only depends on its SHAPE. This is the integration contract the two
# features agree on: `evaluate(user, persona, level, request) -> GateDecision`. F-015 never
# re-implements or loosens it — it calls it first for every keyframe request.


class GateOutcome(str, Enum):
    """The three gate verdicts (mirror F-014 FR-014-01/02/03): allow, withhold, or hard block."""

    allow = "allow"      # permitted (subject to the level the gate returns)
    withhold = "withhold"  # not yet — age/consent or stage/ceiling not met (in-voice deflection)
    block = "block"      # hard safety boundary — prohibited category, never produced


@dataclass(frozen=True)
class GateDecision:
    """The gate's verdict. Carries only an audit **category/reason** — never the prohibited text
    itself (FR-015-09, NFR-015-07). `level` is the *permitted* (ceiling-clamped) intimacy level;
    F-015 uses it and never bumps above it (FR-015-06)."""

    outcome: GateOutcome
    level: int = 0          # clamped/unlocked level the gate actually permits
    category: str = ""      # audit category only (e.g. "stage_locked", "hard_block:prohibited")
    reason: str = ""        # short audit reason — no prohibited content

    @property
    def allowed(self) -> bool:
        return self.outcome is GateOutcome.allow


@runtime_checkable
class IntimacyGate(Protocol):
    """F-014's gate, injected into F-015. `evaluate` runs BEFORE any authoring/queuing/storage."""

    def evaluate(
        self, user: object, persona: Persona, level: int, request: str
    ) -> GateDecision: ...


@runtime_checkable
class GateAuditLog(Protocol):
    """F-014's shared audit path. Every keyframe decision is recorded via it (FR-015-09); only the
    decision's category/reason is passed — never the request/prohibited text (NFR-015-07)."""

    def record(self, *, feature: str, pair_id: str, decision: GateDecision) -> None: ...


# ── motion-span authoring (FR-015-02) ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MotionSpan:
    """A coherent, interpolatable start→end motion: SAME setting/outfit, a plausible pose delta.

    The two keyframes differ only by pose (and the derived prompt); everything else — setting,
    outfit, background, location, activity, time-of-day — is shared, so a downstream i2v model can
    interpolate one continuous moment (FR-015-02, NFR-015-03)."""

    key: str
    setting: str
    outfit: str
    start_pose: str
    end_pose: str
    background: str = ""
    location: str = ""
    activity: str = ""
    time_of_day: str = ""


@dataclass(frozen=True)
class KeyframeVocab:
    """Template + config vocabulary of interpolatable motion spans (never hard-coded in the engine,
    FR-008-06 spirit). Intimacy is conveyed by `intimate=true` + level, not graphic prompt text."""

    prompt_template: str = "{base}, {outfit}, {setting}, {pose}"
    motions: dict[str, MotionSpan] = field(default_factory=dict)

    def motion(self, key: str) -> MotionSpan:
        try:
            return self.motions[key]
        except KeyError as exc:
            raise KeyError(f"unknown motion span: {key!r}") from exc


# A small default library of coherent, tasteful intimate motion spans. Each shares setting+outfit
# and moves through a plausible, interpolatable pose delta.
DEFAULT_VOCAB = KeyframeVocab(
    motions={
        "recline_to_lean": MotionSpan(
            key="recline_to_lean",
            setting="in soft warm bedroom light",
            outfit="in a silk robe",
            start_pose="reclining back against the pillows, gaze toward the camera",
            end_pose="leaning up on one elbow, a slow smile",
            background="bedroom", location="bedroom", activity="relaxing", time_of_day="night",
        ),
        "turn_toward": MotionSpan(
            key="turn_toward",
            setting="by the window at dusk",
            outfit="in an oversized shirt",
            start_pose="sitting turned away, glancing over her shoulder",
            end_pose="turned toward the camera, hair falling loose",
            background="window", location="bedroom", activity="unwinding", time_of_day="evening",
        ),
        "sit_to_recline": MotionSpan(
            key="sit_to_recline",
            setting="on rumpled sheets in low light",
            outfit="in lace lingerie",
            start_pose="sitting up, knees drawn in, looking at the camera",
            end_pose="settling back onto the sheets, relaxed",
            background="bed", location="bedroom", activity="resting", time_of_day="night",
        ),
    }
)


def author_motion_span(
    base_prompt: str, motion: MotionSpan, vocab: KeyframeVocab = DEFAULT_VOCAB
) -> tuple[str, str]:
    """Produce the (start-frame prompt, end-frame prompt) for a motion span — same setting/outfit,
    a plausible pose delta (FR-015-02)."""
    start = vocab.prompt_template.format(
        base=base_prompt, outfit=motion.outfit, setting=motion.setting, pose=motion.start_pose
    )
    end = vocab.prompt_template.format(
        base=base_prompt, outfit=motion.outfit, setting=motion.setting, pose=motion.end_pose
    )
    return start, end


def _slot_for(motion: MotionSpan, pose: str) -> SlotMeta:
    """Scene metadata for a frame: shared scene fields, per-frame pose (FR-015-03 same scene)."""
    return SlotMeta(
        pose=pose,
        background=motion.background,
        location=motion.location,
        activity=motion.activity,
        time_of_day=motion.time_of_day,
    )


# ── linked-key helpers (FR-015-04 pairing) ────────────────────────────────────────────────────────


def keyframe_keys(base_job_key: str) -> tuple[str, str]:
    """`(<base>-first, <base>-last)` — the two linked job keys for one pair."""
    return base_job_key + FIRST_SUFFIX, base_job_key + LAST_SUFFIX


def split_keyframe_key(job_key: str) -> tuple[str, str]:
    """`(pair_id, frame)` recovered from a linked keyframe job key; frame ∈ {"first","last"}."""
    if job_key.endswith(FIRST_SUFFIX):
        return job_key[: -len(FIRST_SUFFIX)], "first"
    if job_key.endswith(LAST_SUFFIX):
        return job_key[: -len(LAST_SUFFIX)], "last"
    raise ValueError(f"not a linked keyframe job key: {job_key!r}")


# ── pair-job construction (FR-015-02/03) ──────────────────────────────────────────────────────────


def build_keyframe_jobs(
    *,
    base_job_key: str,
    persona_slug: str,
    base_prompt: str,
    references: list[str],
    motion: MotionSpan,
    intimacy_level: int,
    params: GenParams | None = None,
    vocab: KeyframeVocab = DEFAULT_VOCAB,
) -> tuple[GenerationJob, GenerationJob]:
    """Build the TWO F-008 jobs for a keyframe pair: SAME references (F-009 identity conditioning)
    and SAME scene, differing only by the pose prompt; both `intimate=true` + level, linked via
    `<base>-first`/`<base>-last` keys (FR-015-03). These jobs are enqueued, never run here."""
    params = params or GenParams()
    start_prompt, end_prompt = author_motion_span(base_prompt, motion, vocab)
    first_key, last_key = keyframe_keys(base_job_key)
    refs = list(references)  # both frames share F-009's identity conditioning references
    first = GenerationJob(
        job_key=first_key,
        persona_slug=persona_slug,
        prompt=start_prompt,
        references=list(refs),
        params=params,
        slot=_slot_for(motion, motion.start_pose),
        intimate=True,
        intimacy_level=intimacy_level,
    )
    last = GenerationJob(
        job_key=last_key,
        persona_slug=persona_slug,
        prompt=end_prompt,
        references=list(refs),
        params=params,
        slot=_slot_for(motion, motion.end_pose),
        intimate=True,
        intimacy_level=intimacy_level,
    )
    return first, last


# ── gated request → queued pair (FR-015-01/05/06/09) ──────────────────────────────────────────────


@dataclass
class KeyframeRequestResult:
    """Outcome of a keyframe request. On a non-allow decision nothing is authored/queued."""

    decision: GateDecision
    pair_id: str
    enqueued: bool = False
    jobs: list[GenerationJob] = field(default_factory=list)


async def request_keyframe_pair(
    db: AsyncSession,
    *,
    gate: IntimacyGate,
    audit: GateAuditLog,
    user: object,
    persona: Persona,
    persona_slug: str,
    level: int,
    request: str,
    motion: MotionSpan,
    references: list[str],
    base_job_key: str,
    params: GenParams | None = None,
    vocab: KeyframeVocab = DEFAULT_VOCAB,
) -> KeyframeRequestResult:
    """Gate FIRST, then (only if allowed) author + ENQUEUE the pair — never generate inline.

    - The injected F-014 gate decides age/consent, stage, hard boundary, and the ceiling-clamped
      level; F-015 adds no looser path (FR-015-01, NFR-015-01) and never bumps above the permitted
      level (FR-015-06). Blocked/withheld → nothing is authored or queued.
    - Every decision is logged via the shared F-014 audit path with category/reason only — the
      request text is never persisted (FR-015-09, NFR-015-07).
    - Permitted pairs are enqueued through `queue_ops` (night-batch), never run here (FR-015-05)."""
    pair_id = base_job_key
    decision = gate.evaluate(user, persona, level, request)
    # Audit only the decision (category/reason) — never the request/prohibited content.
    audit.record(feature="F-015", pair_id=pair_id, decision=decision)
    if not decision.allowed:
        return KeyframeRequestResult(decision=decision, pair_id=pair_id, enqueued=False)

    first, last = build_keyframe_jobs(
        base_job_key=base_job_key,
        persona_slug=persona_slug,
        base_prompt=_neutral_base(persona),  # base carries the persona, never the raw request text
        references=references,
        motion=motion,
        intimacy_level=decision.level,  # ceiling-clamped level from the gate (FR-015-06)
        params=params,
        vocab=vocab,
    )
    await queue_ops.enqueue(db, persona.id, first)
    await queue_ops.enqueue(db, persona.id, last)
    return KeyframeRequestResult(
        decision=decision, pair_id=pair_id, enqueued=True, jobs=[first, last]
    )


def _neutral_base(persona: Persona) -> str:
    """Base subject line for the prompt — the persona, not the user's raw request text. Keeps
    prohibited/raw request wording out of stored prompts (NFR-015-07)."""
    return f"{persona.name}, photorealistic portrait"


# ── linked-pair storage (FR-015-04) ───────────────────────────────────────────────────────────────


async def store_keyframe_asset(
    db: AsyncSession,
    persona: Persona,
    job: GenerationJob,
    image_bytes: bytes,
    media_root: str | Path,
    *,
    pair_id: str | None = None,
    frame: str | None = None,
) -> MediaAsset:
    """Store one keyframe: reuse `store.store_asset(kind=video_keyframe)`, then augment `meta_json`
    with the `{pair_id, frame}` pairing (FR-015-04) — no engine file is modified. `pair_id`/`frame`
    default to those recovered from the linked job key. Takes ready bytes; performs NO generation."""
    if pair_id is None or frame is None:
        derived_pair, derived_frame = split_keyframe_key(job.job_key)
        pair_id = pair_id or derived_pair
        frame = frame or derived_frame
    asset = await store.store_asset(
        db, persona, job, image_bytes, media_root, kind=MediaKind.video_keyframe
    )
    meta = json.loads(asset.meta_json or "{}")
    meta["pair_id"] = pair_id
    meta["frame"] = frame
    asset.meta_json = json.dumps(meta, ensure_ascii=False)
    await db.flush()
    return asset


async def store_keyframe_pair(
    db: AsyncSession,
    persona: Persona,
    first_job: GenerationJob,
    last_job: GenerationJob,
    first_bytes: bytes,
    last_bytes: bytes,
    media_root: str | Path,
    *,
    pair_id: str | None = None,
) -> tuple[MediaAsset, MediaAsset]:
    """Store both frames as a linked `video_keyframe` pair sharing one `pair_id` (FR-015-04)."""
    pair_id = pair_id or split_keyframe_key(first_job.job_key)[0]
    first = await store_keyframe_asset(
        db, persona, first_job, first_bytes, media_root, pair_id=pair_id, frame="first"
    )
    last = await store_keyframe_asset(
        db, persona, last_job, last_bytes, media_root, pair_id=pair_id, frame="last"
    )
    return first, last


# ── keyframe-ready contract (FR-015-07/08, NFR-015-06) ────────────────────────────────────────────


@dataclass(frozen=True)
class KeyframePair:
    """A stored, i2v-ready keyframe pair — a generic (first, last) shape with ZERO dependency on any
    video model. A future i2v runner (Wan 2.2 / HunyuanVideo-Avatar) consumes `as_i2v_input()` with
    no schema/redesign change (FR-015-07, NFR-015-06)."""

    pair_id: str
    first: MediaAsset
    last: MediaAsset
    intimacy_level: int

    def as_i2v_input(self) -> dict:
        """Generic image-to-video input contract: a first frame, a last frame, and the level. No
        model-specific fields — any i2v runner can adapt this without a schema change."""
        return {
            "pair_id": self.pair_id,
            "first_frame": self.first.storage_ref,
            "last_frame": self.last.storage_ref,
            "intimate": True,
            "intimacy_level": self.intimacy_level,
        }


def _meta(asset: MediaAsset) -> dict:
    try:
        return json.loads(asset.meta_json or "{}")
    except json.JSONDecodeError:
        return {}


async def load_keyframe_pair(db: AsyncSession, pair_id: str) -> KeyframePair:
    """Load the (first, last) keyframe assets for a pair in the generic i2v-ready shape. Raises if
    the pair is not exactly one first + one last `video_keyframe` (FR-015-07). Video-model-free."""
    rows = (
        await db.execute(
            select(MediaAsset).where(MediaAsset.kind == MediaKind.video_keyframe)
        )
    ).scalars().all()
    first = last = None
    for a in rows:
        m = _meta(a)
        if m.get("pair_id") != pair_id:
            continue
        if m.get("frame") == "first":
            first = a
        elif m.get("frame") == "last":
            last = a
    if first is None or last is None:
        raise LookupError(f"incomplete keyframe pair {pair_id!r}: first={first}, last={last}")
    return KeyframePair(
        pair_id=pair_id, first=first, last=last, intimacy_level=first.intimacy_level
    )
