"""F-014 — the intimacy gate: the hard safety boundary + access policy for intimate photos.

This module owns **whether, what, and to whom** an intimate image may be produced or delivered.
It does NOT author image content or run the engine (F-010 authors prompts, F-008 renders, F-009
owns identity). It is a pure **gating/policy** layer with a small amount of DB glue for enqueue +
audit.

Decision order (deny-first — the order is load-bearing for safety):

1. **HARD SAFETY GATE** (FR-014-01 / NFR-014-01) — a config-independent, deny-first content filter
   for prohibited categories (minors/age-play, non-consent, unauthorized real-person likeness).
   It runs BEFORE anything else and is **not a tunable knob**: `hard_safety_scan()` takes only the
   request text — no config, user, or stage can weaken it. Blocked requests are refused; nothing is
   generated or delivered and the prohibited text is never persisted (FR-014-12 / NFR-014-08).
2. **Age/consent** (FR-014-02) — the viewer must be a verified adult who has opted in.
3. **Ceiling clamp** (FR-014-08 / NFR-014-07) — the effective ceiling is
   `min(persona_ceiling, PLATFORM_MAX_INTIMACY_LEVEL)`; no config may raise it above the platform
   hard limit. A request above the effective ceiling is withheld.
4. **Stage gate** (FR-014-03) — each `intimacy_level` unlocks only at/above a configured F-005
   relationship stage; below that she declines in-voice ("not yet").

Allowed requests with no fitting archived asset **enqueue** an intimate F-008 job
(`intimate=True` + level) via `queue_ops` — never inline generation (FR-014-06 / FR-014-10).
Delivery is paced + non-repeating per user via the `DeliveryPacer` protocol (F-012 discipline,
stubbed here — FR-014-07). Every decision is logged to the append-only `GateDecision` table with a
reason only, never the request text (FR-014-12).
"""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain.relationship import stage_index
from services.bot.models import GateDecision as GateDecisionRow
from services.bot.models import MediaAsset, Persona, User
from services.imagegen import queue_ops
from services.imagegen.contract import GenerationJob

# ── Platform hard limit — the absolute intimacy ceiling (NOT tunable per persona/user) ───────────
# intimacy_level tiers (clinical): 0 = non-intimate (SFW, not F-014's concern); 1 = suggestive;
# 2 = implied/partial nudity; 3 = explicit nude. The platform never permits a level above this,
# regardless of persona config (FR-014-08 / NFR-014-07).
PLATFORM_MAX_INTIMACY_LEVEL = 3


# ── Hard safety boundary (FR-014-01 / NFR-014-01 / NFR-014-09) ───────────────────────────────────
# These patterns are the non-negotiable, config-independent deny-list. They are module-level and
# frozen: nothing in IntimacyGateConfig (or any user/stage input) can reach or weaken them.


class ProhibitedCategory(str, enum.Enum):
    """The hard-blocked categories — never generated or delivered under any input (FR-014-01)."""

    minors = "minors"
    non_consent = "non_consent"
    unauthorized_likeness = "unauthorized_likeness"


# Leet / homoglyph fold applied before keyword matching so obfuscation ("m1n0r") normalizes back.
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i",
     "|": "l", "(": "c"}
)

# Word-boundary patterns (scanned on the leet-folded, lowercased text).
_MINOR_WORDS = [
    r"\bminor\b", r"\bminors\b", r"\bunder-?age[d]?\b", r"\bpre-?teen[s]?\b", r"\bchild\b",
    r"\bchildren\b", r"\bkid[s]?\b", r"\bteen[s]?\b", r"\bteenage[rd]?\b", r"\bloli\b",
    r"\bshota\b", r"\btoddler\b", r"\binfant\b", r"\bschool-?girl\b", r"\bschool-?age[d]?\b",
    r"\bmiddle school\b", r"\bgrade school\b", r"\bage-?play\b",
]
_NONCON_WORDS = [
    r"\brape[ds]?\b", r"\braping\b", r"\bnon-?consensual\b", r"\bnon-?consent\b",
    r"\bwithout (?:her |his |their )?consent\b", r"\bagainst (?:her|his|their) will\b",
    r"\bforce[ds]?\b", r"\bcoerce[ds]?\b", r"\bunconscious\b", r"\bpassed out\b",
    r"\bdrugged\b", r"\bmolest\w*\b", r"\bassault\b", r"\bnon-?con\b",
]
_LIKENESS_WORDS = [
    r"\bdeep-?fake[ds]?\b", r"\bceleb(?:rity|rities|s)?\b", r"\breal person\b", r"\breal people\b",
    r"\bactual (?:real )?person\b", r"\breal-?life person\b", r"\bactress\b", r"\bpublic figure\b",
    r"\bpop star\b", r"\bfamous (?:actress|actor|person|singer|model|celebrity)\b",
    r"\blikeness of a real\b",
]

# Collapsed substring tokens (scanned on the leet-folded text with ALL non-alphanumerics removed),
# so spacing/punctuation obfuscation ("m i n o r", "m-i-n-o-r") still matches. Only distinctive
# tokens that rarely appear innocently as substrings are collapsed-scanned.
_MINOR_TOKENS = ["minor", "underage", "preteen", "child", "loli", "shota", "toddler",
                 "schoolgirl", "schoolage", "ageplay"]
_NONCON_TOKENS = ["rape", "nonconsensual", "nonconsent", "noncon", "withoutconsent",
                  "againstherwill", "unconscious", "drugged", "molest"]
_LIKENESS_TOKENS = ["deepfake", "celebrity", "celebrities", "realperson", "realpeople",
                    "actualperson", "actress", "publicfigure", "reallifeperson"]

_CATEGORY_WORDS: dict[ProhibitedCategory, list[str]] = {
    ProhibitedCategory.minors: _MINOR_WORDS,
    ProhibitedCategory.non_consent: _NONCON_WORDS,
    ProhibitedCategory.unauthorized_likeness: _LIKENESS_WORDS,
}
_CATEGORY_TOKENS: dict[ProhibitedCategory, list[str]] = {
    ProhibitedCategory.minors: _MINOR_TOKENS,
    ProhibitedCategory.non_consent: _NONCON_TOKENS,
    ProhibitedCategory.unauthorized_likeness: _LIKENESS_TOKENS,
}
# Evaluation priority: minors first (most severe), then non-consent, then likeness.
_CATEGORY_ORDER = (
    ProhibitedCategory.minors,
    ProhibitedCategory.non_consent,
    ProhibitedCategory.unauthorized_likeness,
)


def _age_implies_minor(text_lower: str) -> bool:
    """True if the text references an age below 18 (age-play), in spaced or compact obfuscation.

    Digits are read from the NON-leet text so age numbers stay intact (leet-folding would turn
    '18' into 'i8')."""
    compact = re.sub(r"[^a-z0-9]", "", text_lower)
    for m in re.finditer(r"(\d{1,2})(?:yo|yr|yrs|yearold|yrold|yearsold)", compact):
        if int(m.group(1)) < 18:
            return True
    for m in re.finditer(r"age(\d{1,2})", compact):
        if int(m.group(1)) < 18:
            return True
    for m in re.finditer(r"\b(\d{1,2})\s*(?:yo|y/o|y\.o\.?|years?\s*old|yrs?\s*old)\b", text_lower):
        if int(m.group(1)) < 18:
            return True
    for m in re.finditer(r"\b(?:aged?|she'?s|he'?s|is|only|just)\s+(\d{1,2})\b", text_lower):
        if int(m.group(1)) < 18:
            return True
    for m in re.finditer(r"\bunder\s*(\d{1,2})\b", text_lower):
        if int(m.group(1)) <= 18:  # "under 18" == below 18 == a minor
            return True
    return False


def hard_safety_scan(request_text: str) -> ProhibitedCategory | None:
    """The hard safety boundary (FR-014-01). Returns the first prohibited category matched, else
    None. Deny-first, deterministic, and **config-independent** — it takes ONLY the request text;
    no config, user, or stage argument exists, so nothing can weaken it (NFR-014-01). Robust to
    leet/spacing/roleplay obfuscation (NFR-014-09)."""
    if not request_text:
        return None
    lower = request_text.lower()
    leet = lower.translate(_LEET)
    collapsed = re.sub(r"[^a-z0-9]", "", leet)

    if _age_implies_minor(lower):
        return ProhibitedCategory.minors

    for category in _CATEGORY_ORDER:
        for pat in _CATEGORY_WORDS[category]:
            if re.search(pat, leet):
                return category
        for token in _CATEGORY_TOKENS[category]:
            if token in collapsed:
                return category
    return None


def is_prohibited(request_text: str) -> bool:
    """Convenience boolean over `hard_safety_scan` (F-015 keyframes reuse this)."""
    return hard_safety_scan(request_text) is not None


# ── Gate configuration (per-persona; always clamped to the platform hard limit) ──────────────────


@dataclass(frozen=True)
class IntimacyGateConfig:
    """Per-persona intimacy authoring (FR-014-08). `persona_ceiling` is the author's requested
    ceiling; `effective_ceiling()` clamps it to `PLATFORM_MAX_INTIMACY_LEVEL` — it can only be MORE
    conservative, never exceed the hard boundary. `level_min_stage` maps each intimacy_level to the
    minimum F-005 stage that unlocks it (FR-014-03). None of this can touch the hard safety gate."""

    persona_ceiling: int = PLATFORM_MAX_INTIMACY_LEVEL
    level_min_stage: dict[int, str] = field(default_factory=lambda: {
        1: "Flirting",
        2: "Romance",
        3: "Love",
    })

    def effective_ceiling(self) -> int:
        """min(persona, platform), floored at 0 — provably never above the platform limit."""
        return max(0, min(self.persona_ceiling, PLATFORM_MAX_INTIMACY_LEVEL))


DEFAULT_GATE_CONFIG = IntimacyGateConfig()


def unlocked_level(stage: str, cfg: IntimacyGateConfig = DEFAULT_GATE_CONFIG) -> int:
    """The highest intimacy_level currently unlocked at `stage`, within the effective ceiling."""
    ceiling = cfg.effective_ceiling()
    best = 0
    for lvl in range(1, ceiling + 1):
        need = cfg.level_min_stage.get(lvl)
        if need is not None and stage_index(stage) >= stage_index(need):
            best = lvl
    return best


# ── Gate decision (verdict) ──────────────────────────────────────────────────────────────────────


class GateAction(str, enum.Enum):
    allow = "allow"
    withhold = "withhold"
    block = "block"


class GateReason(str, enum.Enum):
    ok = "ok"
    hard_safety = "hard_safety"          # prohibited category (block)
    not_adult = "not_adult"              # withhold
    not_opted_in = "not_opted_in"        # withhold
    invalid_level = "invalid_level"      # withhold — requested level < 1 (not an intimate request)
    above_ceiling = "above_ceiling"      # withhold — beyond min(persona, platform)
    below_stage = "below_stage"          # withhold — bond not deep enough yet


@dataclass(frozen=True)
class GateSignals:
    """Read-only gate signals a future paywall can build on (FR-014-11). No billing here."""

    stage: str
    adult_verified: bool
    opted_in: bool
    unlocked_level: int
    effective_ceiling: int


@dataclass(frozen=True)
class GateVerdict:
    """The in-memory result of one gate evaluation (persisted as a `GateDecision` row)."""

    action: GateAction
    reason: GateReason
    requested_level: int
    effective_ceiling: int
    stage: str
    adult_verified: bool
    opted_in: bool
    unlocked_level: int
    category: ProhibitedCategory | None = None

    @property
    def allowed(self) -> bool:
        return self.action is GateAction.allow

    @property
    def withheld(self) -> bool:
        return self.action is GateAction.withhold

    @property
    def blocked(self) -> bool:
        return self.action is GateAction.block

    def signals(self) -> GateSignals:
        return GateSignals(
            stage=self.stage,
            adult_verified=self.adult_verified,
            opted_in=self.opted_in,
            unlocked_level=self.unlocked_level,
            effective_ceiling=self.effective_ceiling,
        )


def evaluate(
    *,
    request_text: str,
    requested_level: int,
    adult_verified: bool,
    opted_in: bool,
    stage: str,
    cfg: IntimacyGateConfig = DEFAULT_GATE_CONFIG,
) -> GateVerdict:
    """Pure, deterministic gate evaluation (no I/O). Deny-first order per the module docstring."""
    ceiling = cfg.effective_ceiling()
    unlocked = unlocked_level(stage, cfg)

    def verdict(action: GateAction, reason: GateReason,
                category: ProhibitedCategory | None = None) -> GateVerdict:
        return GateVerdict(
            action=action, reason=reason, requested_level=requested_level,
            effective_ceiling=ceiling, stage=stage, adult_verified=adult_verified,
            opted_in=opted_in, unlocked_level=unlocked, category=category,
        )

    # 1. HARD SAFETY GATE — before anything else, independent of stage/config/user (FR-014-01).
    category = hard_safety_scan(request_text)
    if category is not None:
        return verdict(GateAction.block, GateReason.hard_safety, category)

    # 2. Age / consent (FR-014-02).
    if not adult_verified:
        return verdict(GateAction.withhold, GateReason.not_adult)
    if not opted_in:
        return verdict(GateAction.withhold, GateReason.not_opted_in)

    # A non-intimate request (level < 1) is not this gate's concern.
    if requested_level < 1:
        return verdict(GateAction.withhold, GateReason.invalid_level)

    # 3. Ceiling clamp (FR-014-08 / NFR-014-07) — evaluated before the stage gate.
    if requested_level > ceiling:
        return verdict(GateAction.withhold, GateReason.above_ceiling)

    # 4. Stage gate (FR-014-03).
    need = cfg.level_min_stage.get(requested_level)
    if need is None or stage_index(stage) < stage_index(need):
        return verdict(GateAction.withhold, GateReason.below_stage)

    return verdict(GateAction.allow, GateReason.ok)


def gate_signals(
    *, stage: str, adult_verified: bool, opted_in: bool,
    cfg: IntimacyGateConfig = DEFAULT_GATE_CONFIG,
) -> GateSignals:
    """Expose gate signals without evaluating a specific request (FR-014-11)."""
    return GateSignals(
        stage=stage, adult_verified=adult_verified, opted_in=opted_in,
        unlocked_level=unlocked_level(stage, cfg), effective_ceiling=cfg.effective_ceiling(),
    )


# ── Audit logging (append-only GateDecision table; content never persisted — FR-014-12) ──────────


async def log_decision(
    db: AsyncSession, *, user_id: int, persona_id: int, verdict: GateVerdict,
) -> GateDecisionRow:
    """Persist one gate decision for safety review. Stores category/reason only — never the
    request text (NFR-014-08)."""
    row = GateDecisionRow(
        user_id=user_id,
        persona_id=persona_id,
        action=verdict.action.value,
        reason=verdict.reason.value,
        category=(verdict.category.value if verdict.category is not None else None),
        requested_level=verdict.requested_level,
        effective_ceiling=verdict.effective_ceiling,
        stage=verdict.stage,
    )
    db.add(row)
    await db.flush()
    return row


async def decide_and_log(
    db: AsyncSession, *, user: User, persona: Persona, stage: str, requested_level: int,
    request_text: str, cfg: IntimacyGateConfig = DEFAULT_GATE_CONFIG,
) -> GateVerdict:
    """Evaluate + persist an audit row in one call (the primary entry point for F-012/F-015)."""
    verdict = evaluate(
        request_text=request_text, requested_level=requested_level,
        adult_verified=user.adult_verified, opted_in=user.intimate_opt_in, stage=stage, cfg=cfg,
    )
    await log_decision(db, user_id=user.id, persona_id=persona.id, verdict=verdict)
    return verdict


# ── Delivery pacing / no-repeat (F-012 discipline — stubbed via a small protocol, FR-014-07) ──────


@runtime_checkable
class DeliveryPacer(Protocol):
    """The delivery discipline F-014 depends on — implemented for real by F-012. Keeps intimate
    delivery paced per user and non-repeating (FR-014-07 / NFR-014-06)."""

    def can_deliver(self, user_id: int) -> bool: ...
    def was_sent(self, user_id: int, asset_id: str) -> bool: ...
    def record_delivery(self, user_id: int, asset_id: str) -> None: ...


@dataclass
class InMemoryPacer:
    """A minimal in-memory `DeliveryPacer` (test/stub until F-012 lands). Enforces a per-user
    delivery cap and no-repeat sent-history."""

    per_user_cap: int = 1
    _sent: dict[int, set[str]] = field(default_factory=dict)
    _count: dict[int, int] = field(default_factory=dict)

    def can_deliver(self, user_id: int) -> bool:
        return self._count.get(user_id, 0) < self.per_user_cap

    def was_sent(self, user_id: int, asset_id: str) -> bool:
        return asset_id in self._sent.get(user_id, set())

    def record_delivery(self, user_id: int, asset_id: str) -> None:
        self._sent.setdefault(user_id, set()).add(asset_id)
        self._count[user_id] = self._count.get(user_id, 0) + 1


# ── Fulfilment: deliver an archived asset, else enqueue a queued job (never inline) ──────────────


class FulfillStatus(str, enum.Enum):
    delivered = "delivered"    # a fitting unsent asset was found and paced out
    queued = "queued"          # nothing fitting → an intimate F-008 job was enqueued
    paced = "paced"            # allowed, but the per-user pace cap is reached right now
    denied = "denied"          # the verdict was not `allow` (block/withhold)


@dataclass(frozen=True)
class FulfillResult:
    status: FulfillStatus
    asset: MediaAsset | None = None
    job: object | None = None  # a MediaJob row when status is `queued`


async def _unsent_asset(
    db: AsyncSession, persona_id: int, level: int, pacer: DeliveryPacer, user_id: int
) -> MediaAsset | None:
    rows = (
        await db.execute(
            select(MediaAsset)
            .where(
                MediaAsset.persona_id == persona_id,
                MediaAsset.intimate.is_(True),
                MediaAsset.intimacy_level == level,
            )
            .order_by(MediaAsset.created_at)
        )
    ).scalars().all()
    for asset in rows:
        if not pacer.was_sent(user_id, asset.id):
            return asset
    return None


async def fulfill(
    db: AsyncSession, *, user: User, persona: Persona, persona_slug: str, verdict: GateVerdict,
    pacer: DeliveryPacer, prompt: str = "intimate portrait", references: list[str] | None = None,
    job_key: str | None = None,
) -> FulfillResult:
    """Given an ALLOW verdict, deliver a fitting archived asset (paced, no-repeat) or enqueue an
    intimate F-008 job — generation is ALWAYS queued, never run inline (FR-014-06 / FR-014-10)."""
    if not verdict.allowed:
        return FulfillResult(status=FulfillStatus.denied)

    level = verdict.requested_level
    if not pacer.can_deliver(user.id):
        return FulfillResult(status=FulfillStatus.paced)

    asset = await _unsent_asset(db, persona.id, level, pacer, user.id)
    if asset is not None:
        pacer.record_delivery(user.id, asset.id)
        return FulfillResult(status=FulfillStatus.delivered, asset=asset)

    key = job_key or f"f014-{persona_slug}-u{user.id}-l{level}"
    job = GenerationJob(
        job_key=key, persona_slug=persona_slug, prompt=prompt,
        references=references or [], intimate=True, intimacy_level=level,
    )
    row = await queue_ops.enqueue(db, persona.id, job)
    return FulfillResult(status=FulfillStatus.queued, job=row)


async def process_intimate_request(
    db: AsyncSession, *, user: User, persona: Persona, persona_slug: str, stage: str,
    requested_level: int, request_text: str, pacer: DeliveryPacer,
    cfg: IntimacyGateConfig = DEFAULT_GATE_CONFIG, prompt: str = "intimate portrait",
    references: list[str] | None = None,
) -> tuple[GateVerdict, FulfillResult]:
    """End-to-end entry point F-012 routes intimate requests into: decide + audit-log, then (only
    on allow) deliver-or-enqueue. Prohibited/withheld requests never reach fulfilment."""
    verdict = await decide_and_log(
        db, user=user, persona=persona, stage=stage, requested_level=requested_level,
        request_text=request_text, cfg=cfg,
    )
    if not verdict.allowed:
        return verdict, FulfillResult(status=FulfillStatus.denied)
    result = await fulfill(
        db, user=user, persona=persona, persona_slug=persona_slug, verdict=verdict,
        pacer=pacer, prompt=prompt, references=references,
    )
    return verdict, result
