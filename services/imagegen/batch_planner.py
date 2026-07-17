"""F-011 — Daily SFW Photo Batch: the NIGHTLY PLANNER that fills tomorrow's archive.

F-011 is the *batch-consumer* side of the "image generation is a scheduled night job" decision
(architecture.md §3.9, §6.1, DFD-3). It **orchestrates**; it never renders:

    for each active persona
      → read the target day's Life Engine plan (F-006 DAILY_PLAN, free text w/ HH:MM markers)
      → derive the day's slots (morning → night) from the plan's time markers
      → for each slot commission a configurable SET of SFW shots (default ≈5–6 angles)
      → for each shot: author a prompt (F-010) + pick identity references (F-009)
      → enqueue an F-008 GenerationJob (queue_ops.enqueue — idempotent by job_key)

The F-008 runner (services/imagegen/runner.py — ALREADY implemented) then drains the queue inside
the night/media window with the GPU handoff. F-011 adds NO rendering, NO GPU code, NO delivery.

Boundaries (parallel features, injected here behind small Protocols):
  * **F-010 prompt authoring** — `PromptAuthor.author(persona, slot, shot_index) -> AuthoredShot`.
    A minimal `DefaultPromptAuthor` ships so this planner runs standalone; F-010's real author is
    injected at integration (same call shape).
  * **F-009 identity/reference selection** — `ReferenceProvider.references_for(persona)`. The
    `DefaultReferenceProvider` uses the persona's `face_ref`/`fullbody_ref` (TODO: F-009 replaces
    this with its reference-selection policy behind the same Protocol).

SFW only (F-014 owns intimate content): every planned job asserts `intimate=False`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.bot.domain.life_engine import _split_slots  # slot parsing (FR-006-03/04)
from services.bot.domain.life_engine_store import get_current_plan_text
from services.bot.models import MediaJob, Persona, PersonaStatus
from services.imagegen import queue_ops
from services.imagegen.config import ImageRunnerSettings
from services.imagegen.contract import GenerationJob, GenParams, SlotMeta
from services.imagegen.runner import in_media_window

log = logging.getLogger(__name__)


# ── slot derivation (FR-011-02) ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SlotContext:
    """One derived slot of the persona's day — the unit a shot-set is commissioned for."""

    idx: int              # stable index within the day (job_key component; sorted by start time)
    time_of_day: str      # morning|afternoon|evening|night — coarse tag for context selection
    activity: str         # short activity summary from the plan slot text
    location: str         # best-effort location guess from the slot text ("" if unknown)
    start_hhmm: str       # "HH:MM" local start marker
    text: str             # the raw plan slot text (provenance for the prompt author)


def _time_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


# Small keyword → location map (best-effort; F-010's author refines the real background).
_LOCATION_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("gym", "workout", "training", "yoga", "run", "тренаж", "зал", "спорт"), "gym"),
    (("cafe", "coffee", "café", "barista", "кафе", "кофе"), "cafe"),
    (("office", "work", "desk", "meeting", "офис", "работ"), "office"),
    (("home", "apartment", "kitchen", "couch", "bed", "дом", "кварт", "кухн"), "home"),
    (("park", "street", "walk", "outside", "city", "парк", "улиц", "прогул"), "outdoors"),
    (("restaurant", "dinner", "bar", "ресторан", "ужин", "бар"), "restaurant"),
)


def _guess_location(text: str) -> str:
    low = text.lower()
    for keywords, loc in _LOCATION_HINTS:
        if any(k in low for k in keywords):
            return loc
    return ""


def _summarize_activity(text: str, max_words: int = 8) -> str:
    words = text.replace("\n", " ").split()
    return " ".join(words[:max_words]).strip(" .,;:—-")


def derive_slots(plan_text: str) -> list[SlotContext]:
    """Turn the free-text daily plan into ordered slot contexts (FR-011-02).

    Slots come from the plan's HH:MM time markers (F-006 `_split_slots`, already sorted by start).
    If the plan has no parseable markers but has text, a single whole-day fallback slot is returned
    so the day is never left with zero coverage (NFR-011-02 degrade)."""
    parsed = _split_slots(plan_text)
    if not parsed:
        if plan_text.strip():
            return [SlotContext(0, "day", _summarize_activity(plan_text),
                                _guess_location(plan_text), "", plan_text.strip())]
        return []
    out: list[SlotContext] = []
    for idx, slot in enumerate(parsed):
        out.append(
            SlotContext(
                idx=idx,
                time_of_day=_time_of_day(slot.start.hour),
                activity=_summarize_activity(slot.text),
                location=_guess_location(slot.text),
                start_hhmm=slot.start.strftime("%H:%M"),
                text=slot.text,
            )
        )
    return out


# ── prompt authoring boundary (F-010) ─────────────────────────────────────────────────────────────


@dataclass
class AuthoredShot:
    """What F-010 returns for one shot: the prompt text, negatives, and the slot metadata that
    lands on MEDIA_ASSET.meta_json (F-008 FR-008-08 / F-010 FR-010-08)."""

    prompt: str
    negative: str
    slot: SlotMeta


class PromptAuthor(Protocol):
    """F-010's contract, injected here. Given a persona, a derived slot, and the shot index within
    that slot's set, author one SFW prompt + negatives + slot tags."""

    def author(self, persona: Persona, slot: SlotContext, shot_index: int) -> AuthoredShot: ...


# Rotating camera angles so a slot's set reads as different candid shots, not one pose repeated.
_ANGLES = (
    "casual selfie, arm's length",
    "candid mid-shot, looking away",
    "over-the-shoulder glance",
    "full-body mirror shot",
    "close-up portrait, soft light",
    "wide environmental shot",
)
_DEFAULT_NEGATIVE = "blurry, deformed hands, extra fingers, watermark, text, lowres, nsfw, nude"


class DefaultPromptAuthor:
    """Minimal built-in author so the planner works standalone (replaced by F-010 at integration).

    Produces a plausible SFW candid prompt from the persona + slot + angle, and echoes the slot
    tags (time_of_day/activity/location) onto SlotMeta so context selection (F-012/F-013) works."""

    def author(self, persona: Persona, slot: SlotContext, shot_index: int) -> AuthoredShot:
        angle = _ANGLES[shot_index % len(_ANGLES)]
        activity = slot.activity or "spending her day"
        where = f" at the {slot.location}" if slot.location else ""
        prompt = (
            f"candid {slot.time_of_day} photo of {persona.name}, {activity}{where}, {angle}, "
            f"natural lighting, realistic, SFW"
        )
        meta = SlotMeta(
            pose=angle,
            background=slot.location or slot.time_of_day,
            location=slot.location,
            activity=slot.activity,
            time_of_day=slot.time_of_day,
        )
        return AuthoredShot(prompt=prompt, negative=_DEFAULT_NEGATIVE, slot=meta)


# ── identity / reference boundary (F-009) ─────────────────────────────────────────────────────────


class ReferenceProvider(Protocol):
    """F-009's contract: the identity references to condition generation on for this persona."""

    def references_for(self, persona: Persona) -> list[str]: ...


class DefaultReferenceProvider:
    """TODO(F-009): interim reference selection — use the persona's stored face/full-body refs.

    F-009 will replace this behind the same Protocol with its real reference-selection policy
    (which refs, how many, per pose/angle). For now we forward whichever anchor refs exist so the
    enqueued jobs already carry identity conditioning (F-008 FR-008-05 passes them untouched)."""

    def references_for(self, persona: Persona) -> list[str]:
        return [r for r in (persona.face_ref, persona.fullbody_ref) if r]


# ── config-driven budgets (FR-011-09, NFR-011-06) ─────────────────────────────────────────────────


@dataclass
class BatchPlanConfig:
    """Per-run + per-persona budget knobs — tunable without code changes (architecture.md §4.8)."""

    shots_per_slot: int = 6                # default ≈5–6 angles per slot (FR-011-03)
    slots: tuple[str, ...] | None = None   # restrict to these time_of_day tags (None = all derived)
    plan_days_ahead: int = 1               # 0 = current local day, 1 = tomorrow (feature default)
    base_seed: int = 1000                  # deterministic seeds → reproducible re-runs
    # Per-persona overrides keyed by persona slug, e.g. {"flagship": {"shots_per_slot": 3}}.
    per_persona: dict[str, dict] = field(default_factory=dict)

    def resolve(self, slug: str) -> tuple[int, tuple[str, ...] | None]:
        """Effective (shots_per_slot, slots-filter) for a persona (override wins — FR-011-09)."""
        override = self.per_persona.get(slug, {})
        shots = int(override.get("shots_per_slot", self.shots_per_slot))
        slots = override.get("slots", self.slots)
        return shots, (tuple(slots) if slots is not None else None)


# ── metrics / observability (FR-011-11, NFR-011-08) ───────────────────────────────────────────────


@dataclass
class PersonaPlanResult:
    persona_id: int
    slug: str
    slots_planned: int = 0
    shots_planned: int = 0     # total shots the budget called for
    jobs_enqueued: int = 0     # newly enqueued this run
    jobs_existing: int = 0     # already present (idempotent skip — FR-011-06)
    shots_failed: int = 0      # per-shot planning failures (degraded, FR-011-07)
    failed: bool = False       # whole-persona planning failure (isolated, NFR-011-07)
    error: str = ""


@dataclass
class PlanMetrics:
    planned_at: datetime | None = None
    personas_planned: int = 0
    personas_failed: int = 0
    slots_planned: int = 0
    shots_planned: int = 0
    jobs_enqueued: int = 0
    jobs_existing: int = 0
    shots_failed: int = 0
    per_persona: list[PersonaPlanResult] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "planned_at": self.planned_at,
            "personas_planned": self.personas_planned,
            "personas_failed": self.personas_failed,
            "slots_planned": self.slots_planned,
            "shots_planned": self.shots_planned,
            "jobs_enqueued": self.jobs_enqueued,
            "jobs_existing": self.jobs_existing,
            "shots_failed": self.shots_failed,
            "per_persona": [
                {
                    "slug": r.slug,
                    "slots_planned": r.slots_planned,
                    "shots_planned": r.shots_planned,
                    "jobs_enqueued": r.jobs_enqueued,
                    "jobs_existing": r.jobs_existing,
                    "shots_failed": r.shots_failed,
                    "failed": r.failed,
                }
                for r in self.per_persona
            ],
        }


# ── the planner ───────────────────────────────────────────────────────────────────────────────────


def job_key_for(slug: str, date_key: str, slot_idx: int, shot_idx: int) -> str:
    """Deterministic idempotency key (FR-011-06): re-running the planner reuses the SAME key, so
    `queue_ops.enqueue` dedupes and NO duplicate job/asset is ever created for the same slot/shot."""
    return f"daily-{slug}-{date_key}-{slot_idx}-{shot_idx}"


def _slug_of(persona: Persona) -> str:
    from services.bot.personas_seed import persona_slug

    return persona_slug(persona.name)


class BatchPlanner:
    """Fills tomorrow's SFW photo archive by enqueuing F-008 jobs — it orchestrates, never renders.

    The planner touches only the durable job queue (`queue_ops`) — it holds no GPU and imports no
    backend, so it is safe to run any time (planning is cheap). Generation happens later, in the
    night window, via the F-008 runner draining the queue (see `run_nightly`)."""

    def __init__(
        self,
        config: BatchPlanConfig | None = None,
        settings: ImageRunnerSettings | None = None,
        author: PromptAuthor | None = None,
        references: ReferenceProvider | None = None,
    ) -> None:
        self.config = config or BatchPlanConfig()
        self.settings = settings or ImageRunnerSettings()
        self.author = author or DefaultPromptAuthor()
        self.references = references or DefaultReferenceProvider()

    # -- window gate (FR-011-01) --

    def should_run(self, personas: list[Persona], now: datetime | None = None) -> bool:
        """True only while some active persona is inside her media/sleep window (FR-011-01/10).

        Planning is cheap and idempotent, but the *batch* is a night job: we gate it on the same
        window the F-008 runner uses so generation never contends with the daytime chat model."""
        now = now or datetime.now(timezone.utc)
        return any(
            p.status == PersonaStatus.active
            and in_media_window(now, p.timezone, self.settings)
            for p in personas
        )

    # -- target day resolution --

    def _target_date_key(self, persona: Persona, now: datetime, target_date: str | None) -> str:
        if target_date is not None:
            return target_date
        from services.bot.domain.life_engine import local_date_key

        local = now + timedelta(days=self.config.plan_days_ahead)
        return local_date_key(persona.timezone, local)

    # -- per-persona planning (NFR-011-07 isolation) --

    async def plan_persona(
        self, db: AsyncSession, persona: Persona, now: datetime, target_date: str | None = None,
    ) -> PersonaPlanResult:
        slug = _slug_of(persona)
        result = PersonaPlanResult(persona_id=persona.id, slug=slug)
        try:
            date_key = self._target_date_key(persona, now, target_date)
            plan_text = await get_current_plan_text(db, persona.id, date_key)
            slots = derive_slots(plan_text)
            shots_per_slot, slots_filter = self.config.resolve(slug)
            refs = self.references.references_for(persona)

            for ctx in slots:
                if slots_filter is not None and ctx.time_of_day not in slots_filter:
                    continue
                result.slots_planned += 1
                for shot_idx in range(shots_per_slot):
                    result.shots_planned += 1
                    try:
                        await self._enqueue_shot(db, persona, slug, date_key, ctx, shot_idx,
                                                 refs, result)
                    except Exception as exc:  # noqa: BLE001 — one shot must not abort the slot
                        result.shots_failed += 1
                        log.warning("plan shot failed persona=%s slot=%d shot=%d: %s",
                                    slug, ctx.idx, shot_idx, exc)
        except Exception as exc:  # noqa: BLE001 — one persona must not abort the roster (NFR-011-07)
            result.failed = True
            result.error = str(exc)
            log.error("planning failed for persona=%s: %s", slug, exc)
        return result

    async def _enqueue_shot(
        self, db: AsyncSession, persona: Persona, slug: str, date_key: str,
        ctx: SlotContext, shot_idx: int, refs: list[str], result: PersonaPlanResult,
    ) -> None:
        key = job_key_for(slug, date_key, ctx.idx, shot_idx)
        existing = await db.scalar(select(MediaJob.id).where(MediaJob.job_key == key))
        if existing is not None:
            result.jobs_existing += 1
            return  # idempotent: already planned (FR-011-06)
        shot = self.author.author(persona, ctx, shot_idx)
        job = GenerationJob(
            job_key=key,
            persona_slug=slug,
            prompt=shot.prompt,
            references=list(refs),
            params=GenParams(
                steps=self.settings.default_steps,
                cfg=self.settings.default_cfg,
                width=self.settings.default_width,
                height=self.settings.default_height,
                seed=self.config.base_seed + ctx.idx * 100 + shot_idx,
                negative=shot.negative,
            ),
            slot=shot.slot,
            intimate=False,      # SFW day archive only — intimate content is F-014's gate
            intimacy_level=0,
        )
        await queue_ops.enqueue(db, persona.id, job)
        result.jobs_enqueued += 1

    # -- whole-roster planning --

    async def plan_day(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        now: datetime | None = None,
        target_date: str | None = None,
    ) -> PlanMetrics:
        """Plan the target day's archive for every active persona (FR-011-02..07, isolated)."""
        now = now or datetime.now(timezone.utc)
        metrics = PlanMetrics(planned_at=now)
        async with sessionmaker() as db:
            personas = (
                await db.execute(
                    select(Persona).where(Persona.status == PersonaStatus.active)
                )
            ).scalars().all()
            for persona in personas:
                result = await self.plan_persona(db, persona, now, target_date)
                await db.commit()  # persist per-persona → a later failure keeps earlier work
                metrics.per_persona.append(result)
                if result.failed:
                    metrics.personas_failed += 1
                else:
                    metrics.personas_planned += 1
                metrics.slots_planned += result.slots_planned
                metrics.shots_planned += result.shots_planned
                metrics.jobs_enqueued += result.jobs_enqueued
                metrics.jobs_existing += result.jobs_existing
                metrics.shots_failed += result.shots_failed
        log.info(
            "F-011 batch planned: personas=%d failed=%d slots=%d shots=%d enqueued=%d existing=%d "
            "shots_failed=%d",
            metrics.personas_planned, metrics.personas_failed, metrics.slots_planned,
            metrics.shots_planned, metrics.jobs_enqueued, metrics.jobs_existing,
            metrics.shots_failed,
        )
        return metrics

    # -- end-to-end night pass: gate → plan → drain via the F-008 runner (FR-011-01/08/10) --

    async def run_nightly(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        runner,
        now: datetime | None = None,
        target_date: str | None = None,
    ) -> dict:
        """One night pass: gate on the window, plan the archive, then hand the queue to the F-008
        runner to render inside the same handoff (FR-008-15/16). Returns {plan, run} metrics.

        Returns `{"ran": False}` when outside the media window — the batch waits (NFR-011-03),
        it never renders while the chat model owns the GPU during the day."""
        now = now or datetime.now(timezone.utc)
        async with sessionmaker() as db:
            personas = (await db.execute(select(Persona))).scalars().all()
        if not self.should_run(personas, now=now):
            log.info("F-011 batch skipped — outside the media window (now=%s)", now)
            return {"ran": False, "reason": "outside_media_window"}
        plan = await self.plan_day(sessionmaker, now=now, target_date=target_date)
        run = await runner.run_batch(sessionmaker, now=now)  # F-008 renders inside its handoff
        return {"ran": True, "plan": plan.snapshot(), "run": run}
