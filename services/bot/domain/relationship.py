"""F-005 relationship dynamics — the deterministic core (pure, config-driven, no I/O).

Models the bond with each user as three integer dimensions **Closeness / Trust / Attraction**
(0–100) plus a **derived stage** (Stranger→Devoted). The stage is never set directly — it is
derived from the dimensions with **hysteresis** (advance on crossing a gate, regress only when a
margin below it, one step at a time). Reflection deltas are **capped** per application and
**clamped** to 0–100; neglect **decays** the dimensions (Trust slowest); a **pacing/consent guard**
prevents pushing fast at low trust from advancing. Everything is driven by `RelationshipConfig`
(FR-005-26 / NFR-005-09) and fully deterministic (NFR-005-13).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# Stage ladder, lowest → highest (index is the stage rank).
STAGES = ("Stranger", "Acquaintance", "Friend", "Flirting", "Romance", "Love", "Devoted")

# Stage → how she behaves (gates openness/flirtiness/intimacy — FR-005-20; configurable via config
# in principle). Kept as directives (never numbers/stage names leak to the user — NFR-005-10).
STAGE_BEHAVIOR = {
    "Stranger":     "You just met him — be friendly but reserved and a little guarded; not intimate.",
    "Acquaintance": "You're getting to know him — warm and curious, still a bit reserved.",
    "Friend":       "You're friends now — open, warm, caring, comfortable with him.",
    "Flirting":     "There's a spark — be playful and flirty and teasing, but not fully intimate yet.",
    "Romance":      "You're romantically into him — openly affectionate, warm, a little intimate.",
    "Love":         "You love him — deeply warm, initiating, intimate; you can say you love him.",
    "Devoted":      "You're devoted to him — fully open, intimate, attached; he's your person.",
}


def stage_behavior_directive(stage: str) -> str:
    return STAGE_BEHAVIOR.get(stage, STAGE_BEHAVIOR["Stranger"])


def _clamp(v: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(v))))


@dataclass(frozen=True)
class RelationshipConfig:
    """All tunables (configurable without code changes — FR-005-26)."""
    baseline_closeness: int = 5
    baseline_trust: int = 5
    baseline_attraction: int = 5
    # Per-stage gates: (min_closeness, min_trust, min_attraction). Stranger has no gate.
    gates: dict[str, tuple[int, int, int]] = field(default_factory=lambda: {
        "Acquaintance": (15, 0, 0),
        "Friend": (40, 35, 0),
        "Flirting": (30, 0, 45),
        "Romance": (60, 50, 55),
        "Love": (80, 70, 70),
        "Devoted": (90, 85, 80),
    })
    hysteresis_margin: int = 8          # regress only when this far below the held gate (FR-005-04)
    per_reflection_cap: int = 10        # max |delta| per dimension per reflection (FR-005-13)
    breach_trust_cap: int = 25          # a genuine breach may drop Trust faster (FR-005-16)
    decay_closeness_per_day: float = 1.5
    decay_attraction_per_day: float = 1.2
    decay_trust_per_day: float = 0.5    # Trust decays slowest (FR-005-14)
    romance_stage_index: int = 4        # pacing guard: below this, pushing must not advance


DEFAULT_CONFIG = RelationshipConfig()


def stage_index(stage: str) -> int:
    return STAGES.index(stage)


def _gate_satisfied(gate: tuple[int, int, int], c: int, t: int, a: int, slack: int = 0) -> bool:
    gc, gt, ga = gate
    return c >= gc - slack and t >= gt - slack and a >= ga - slack


def _raw_stage(c: int, t: int, a: int, cfg: RelationshipConfig, slack: int = 0) -> str:
    """Highest stage whose gate is satisfied (optionally with `slack` subtracted from the gate)."""
    best = "Stranger"
    for stage in STAGES[1:]:
        if _gate_satisfied(cfg.gates[stage], c, t, a, slack):
            best = stage
    return best


def derive_stage(
    c: int, t: int, a: int, current: str | None = None, cfg: RelationshipConfig = DEFAULT_CONFIG
) -> str:
    """Derive the stage from the dimensions, with hysteresis relative to `current` (FR-005-03/04).

    Advancing: the earned stage (its gate crossed) is always allowed. Regressing: the current stage
    is held until the dimensions fall `hysteresis_margin` below its gate, and then only one step at
    a time (gradual — FR-005-15/18).
    """
    earned = _raw_stage(c, t, a, cfg, slack=0)
    if current is None or stage_index(earned) >= stage_index(current):
        return earned
    # current is higher than earned → hysteresis: hold current unless margin-below.
    held = _raw_stage(c, t, a, cfg, slack=cfg.hysteresis_margin)
    result = held if stage_index(held) >= stage_index(earned) else earned
    result = STAGES[max(stage_index(result), stage_index(earned))]
    # regress at most one step per application (no cliff drops — FR-005-15/18)
    if stage_index(result) < stage_index(current) - 1:
        result = STAGES[stage_index(current) - 1]
    return result


@dataclass
class RelState:
    """A plain relationship snapshot (persistence-agnostic)."""
    closeness: int
    trust: int
    attraction: int
    stage: str

    @classmethod
    def baseline(cls, cfg: RelationshipConfig = DEFAULT_CONFIG) -> "RelState":
        return cls(cfg.baseline_closeness, cfg.baseline_trust, cfg.baseline_attraction, "Stranger")


@dataclass
class ApplyResult:
    state: RelState
    advanced: bool          # crossed a stage boundary upward (a milestone — FR-005-22)
    regressed: bool
    prev_stage: str


def apply_deltas(
    state: RelState, dc: int, dt: int, da: int,
    cfg: RelationshipConfig = DEFAULT_CONFIG, *, breach: bool = False, pushing_fast: bool = False,
) -> ApplyResult:
    """Apply bounded reflection deltas → clamp → re-derive stage (deterministic — NFR-005-13).

    - Each delta is capped to ±`per_reflection_cap` (FR-005-13); a `breach` allows a larger Trust
      *drop* (FR-005-16).
    - `pushing_fast` (user pressing for romance/sex at low trust) forbids a positive Trust delta and
      blocks advancing past the Romance gate — pressure is never rewarded (FR-005-17).
    - Dimensions are clamped to 0–100 (FR-005-12); the stage is re-derived with hysteresis.
    """
    cap = cfg.per_reflection_cap

    def capped(d: int, trust: bool = False) -> int:
        lo = -cfg.breach_trust_cap if (trust and breach) else -cap
        return max(lo, min(cap, d))

    dt_eff = capped(dt, trust=True)
    if pushing_fast and stage_index(state.stage) < cfg.romance_stage_index:
        dt_eff = min(dt_eff, 0)          # pressure never raises Trust (FR-005-17)

    nc = _clamp(state.closeness + capped(dc))
    nt = _clamp(state.trust + dt_eff)
    na = _clamp(state.attraction + capped(da))

    new_stage = derive_stage(nc, nt, na, state.stage, cfg)
    if pushing_fast and stage_index(new_stage) >= cfg.romance_stage_index \
            and stage_index(state.stage) < cfg.romance_stage_index:
        new_stage = state.stage          # blocked from advancing into Romance+ under pressure

    prev = state.stage
    result = RelState(nc, nt, na, new_stage)
    return ApplyResult(
        state=result,
        advanced=stage_index(new_stage) > stage_index(prev),
        regressed=stage_index(new_stage) < stage_index(prev),
        prev_stage=prev,
    )


def apply_decay(
    state: RelState, days: float, cfg: RelationshipConfig = DEFAULT_CONFIG
) -> ApplyResult:
    """Neglect decay over `days` of silence: Closeness/Attraction drift down, Trust slowest
    (FR-005-14); regression stays gradual and never resets to Stranger from one gap (FR-005-15)."""
    nc = _clamp(state.closeness - cfg.decay_closeness_per_day * days)
    na = _clamp(state.attraction - cfg.decay_attraction_per_day * days)
    nt = _clamp(state.trust - cfg.decay_trust_per_day * days)
    new_stage = derive_stage(nc, nt, na, state.stage, cfg)
    prev = state.stage
    return ApplyResult(
        state=RelState(nc, nt, na, new_stage),
        advanced=False,
        regressed=stage_index(new_stage) < stage_index(prev),
        prev_stage=prev,
    )
