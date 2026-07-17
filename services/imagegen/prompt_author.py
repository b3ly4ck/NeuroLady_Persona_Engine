"""F-010 Generation Prompt Authoring — turn a persona's Life Engine state into model-ready prompts.

Where F-009 holds the *identity* (face/body, via reference conditioning) and F-008 *runs* the model,
F-010 authors the *content* of each shot: the scene, activity, location, outfit, pose, framing/angle,
time-of-day lighting and phone-photo realism cues, plus a negative list. For one life slot it emits a
small **set of distinct framings** (≈5-6) so a slot yields a believable little photo set, not one
repeated frame.

Design invariants (feature §4):
- **Reads life state** (activity / location / mood / time_of_day), never invents her day (FR-010-01).
- **Never restates identity** — the prompt describes scene/pose/camera only; no face/body descriptors
  (identity is F-009's reference conditioning). `assert_no_identity_terms` guards this (FR-010-05).
- **Config-driven** persona style, shot count, realism/negative vocabularies — tune without code
  changes by passing a different `PromptAuthorConfig` / dict (FR-010-06, NFR-010-04).
- **Deterministic**: same slot + seed → byte-identical prompts and per-shot seeds (NFR-010-03).
- **Safe default**: missing/empty life state falls back to the config default scene, never crashes
  (FR-010-09).
- **Pure text composition** — no model calls, no I/O, no network (NFR-010-06).
- **SFW only** — intimate vocabulary is F-014's; `assert_sfw` guards leaks (NFR-010-07).
- Output conforms to the fixed F-008 job contract (`GenerationJob` / `GenParams` / `SlotMeta`),
  so provenance (prompt + slot + seed) is carried into `MEDIA_ASSET.meta_json` (FR-010-08/10/11).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime

from services.imagegen.contract import GenerationJob, GenParams, SlotMeta

# ── life-slot input (what F-006/F-011 hands us) ──────────────────────────────────────────────────


@dataclass(frozen=True)
class LifeSlot:
    """The Life Engine state F-010 authors from (FR-010-01).

    All fields optional so a partial/empty slot degrades to the config default (FR-010-09). The
    caller (F-011) derives these from F-006: `activity` is `current_activity(...)`, `location`/`mood`
    are the slot's place/feeling, `time_of_day` one of morning|afternoon|evening|night.
    """

    activity: str = ""
    location: str = ""
    mood: str = ""
    time_of_day: str = ""

    def is_empty(self) -> bool:
        return not (self.activity.strip() or self.location.strip())


def time_of_day_from_hour(hour: int) -> str:
    """Map a 24h local hour to a coarse time-of-day bucket (FR-010-07 lighting coherence)."""
    h = hour % 24
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"


def slot_from_activity(
    activity: str,
    now_local: datetime | None = None,
    *,
    location: str = "",
    mood: str = "",
    time_of_day: str = "",
) -> LifeSlot:
    """Build a `LifeSlot` from a raw Life-Engine activity string + the persona's local time.

    `time_of_day` is derived from `now_local` when not given explicitly, so a caller that only has the
    free-text current activity still gets time-coherent lighting (FR-010-07)."""
    tod = time_of_day or (time_of_day_from_hour(now_local.hour) if now_local is not None else "")
    return LifeSlot(activity=activity.strip(), location=location.strip(), mood=mood.strip(),
                    time_of_day=tod.strip())


# ── persona visual style (config-driven — FR-010-06 / NFR-010-04) ────────────────────────────────


@dataclass(frozen=True)
class PersonaStyle:
    """A persona's visual style — aesthetic, palette, typical outfits and favorite locations.

    Purely descriptive of look-and-feel, never of identity (no face/body). Tunable per persona via
    config with no code change (FR-010-06)."""

    aesthetic: str = "natural everyday look"
    palette: str = "true-to-life colors"
    outfits: tuple[str, ...] = ("casual everyday outfit",)
    locations: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict) -> "PersonaStyle":
        return cls(
            aesthetic=str(data.get("aesthetic", cls.aesthetic)),
            palette=str(data.get("palette", cls.palette)),
            outfits=tuple(data.get("outfits") or cls.outfits),
            locations=tuple(data.get("locations") or ()),
        )


# ── framing / angle vocabulary (FR-010-04 variety) ───────────────────────────────────────────────


@dataclass(frozen=True)
class Framing:
    """One camera framing/angle. `pose` is the short SlotMeta label; `phrase` is the prompt text."""

    key: str
    phrase: str
    pose: str


# Genuinely different angles/framings — not near-duplicates (FR-010-04, NFR-010-02). Ordered; a
# slot's set rotates through these deterministically by seed.
DEFAULT_FRAMINGS: tuple[Framing, ...] = (
    Framing("selfie_closeup",
            "close-up selfie held at arm's length, front-facing phone camera, looking into the lens",
            "close selfie"),
    Framing("wide_establishing",
            "wide establishing shot of the whole scene, subject small within the environment",
            "wide shot"),
    Framing("candid_side",
            "candid medium shot from the side, three-quarter angle, subject unaware of the camera",
            "candid side"),
    Framing("mirror_fulllength",
            "mirror selfie, phone visible in the reflection, full-length framing",
            "mirror selfie"),
    Framing("low_angle",
            "low-angle shot looking slightly upward, waist-up framing",
            "low angle"),
    Framing("high_angle",
            "high-angle shot looking down, casual overhead snapshot",
            "high angle"),
    Framing("over_shoulder",
            "over-the-shoulder shot from behind, subject facing the scene",
            "over the shoulder"),
    Framing("medium_portrait",
            "medium waist-up framing, relaxed candid stance",
            "medium waist-up"),
)


# ── vocabularies (config-driven — NFR-010-04) ────────────────────────────────────────────────────

DEFAULT_REALISM_CUES: tuple[str, ...] = (
    "candid smartphone photo",
    "shot on a phone camera",
    "natural lighting",
    "authentic amateur snapshot",
    "true-to-life skin texture",
    "slight imperfect framing",
)

DEFAULT_NEGATIVES: tuple[str, ...] = (
    "watermark", "text", "logo", "signature",
    "extra limbs", "extra fingers", "deformed hands", "disfigured",
    "lowres", "blurry artifacts", "jpeg artifacts", "oversaturated",
    "cartoon", "anime", "3d render", "cgi", "plastic skin",
    "duplicate", "cropped face", "out of frame",
)

# Time-of-day → lighting/setting phrase (FR-010-07). Unknown/empty tod → neutral daylight.
DEFAULT_TIME_LIGHTING: dict[str, str] = {
    "morning": "soft warm morning light, gentle early sunlight",
    "afternoon": "bright natural daytime light",
    "evening": "warm golden-hour evening light",
    "night": "low ambient night lighting, artificial indoor and street lights, dark sky outside",
    "": "natural daylight",
}

# Identity descriptors F-010 must NEVER emit — they would fight F-009's reference conditioning
# (FR-010-05). The bare subject noun ("woman") is allowed; only *descriptors* of her are banned.
BANNED_IDENTITY_TERMS: tuple[str, ...] = (
    "blonde", "brunette", "redhead", "ginger", "hair color", "hairstyle", "long hair", "short hair",
    "eyes", "eye color", "blue eyes", "green eyes", "brown eyes",
    "face", "facial", "cheekbones", "jawline", "nose", "lips", "eyebrows", "freckles", "dimples",
    "skin tone", "complexion", "tanned skin", "pale skin",
    "tall", "petite", "slim", "curvy", "athletic build", "figure", "body type", "physique",
    "years old", "year-old", "aged", "her age", "beautiful woman", "gorgeous woman", "pretty face",
    "supermodel", "stunning face",
)

# SFW guard — explicit terms belong to F-014 only and must never leak into F-010 authoring
# (NFR-010-07).
EXPLICIT_TERMS: tuple[str, ...] = (
    "nude", "naked", "topless", "nsfw", "explicit", "erotic", "porn", "sex",
    "breasts", "nipple", "nipples", "genital", "genitals", "cleavage", "underwear", "lingerie",
    "bikini",
)


# ── default scene (safe fallback — FR-010-09) ────────────────────────────────────────────────────

DEFAULT_SCENE = LifeSlot(
    activity="relaxing at home",
    location="cozy living room",
    mood="calm and content",
    time_of_day="evening",
)


@dataclass(frozen=True)
class PromptAuthorConfig:
    """All prompt-authoring tunables — edit/replace to retune without code changes (NFR-010-04)."""

    shot_count: int = 6                       # default set size per slot (FR-010-04, ≈5-6)
    subject_token: str = "candid photo of a woman"   # generic subject; identity is F-009's job
    realism_cues: tuple[str, ...] = DEFAULT_REALISM_CUES
    negatives: tuple[str, ...] = DEFAULT_NEGATIVES
    framings: tuple[Framing, ...] = DEFAULT_FRAMINGS
    time_lighting: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TIME_LIGHTING))
    default_scene: LifeSlot = DEFAULT_SCENE
    default_style: PersonaStyle = field(default_factory=PersonaStyle)
    styles: dict[str, PersonaStyle] = field(default_factory=dict)   # per persona_slug
    params: GenParams = field(default_factory=GenParams)            # template gen knobs

    def style_for(self, persona_slug: str) -> PersonaStyle:
        return self.styles.get(persona_slug, self.default_style)

    @classmethod
    def from_dict(cls, data: dict) -> "PromptAuthorConfig":
        """Build a config from a plain dict (e.g. loaded from a YAML/JSON deployment file)."""
        base = cls()
        styles = {
            slug: PersonaStyle.from_dict(s) for slug, s in (data.get("styles") or {}).items()
        }
        default_style = (
            PersonaStyle.from_dict(data["default_style"])
            if "default_style" in data else base.default_style
        )
        return cls(
            shot_count=int(data.get("shot_count", base.shot_count)),
            subject_token=str(data.get("subject_token", base.subject_token)),
            realism_cues=tuple(data.get("realism_cues") or base.realism_cues),
            negatives=tuple(data.get("negatives") or base.negatives),
            framings=base.framings,
            time_lighting={**base.time_lighting, **(data.get("time_lighting") or {})},
            default_scene=base.default_scene,
            default_style=default_style,
            styles=styles,
        )


DEFAULT_CONFIG = PromptAuthorConfig()


# ── guards (FR-010-05 / NFR-010-07) ──────────────────────────────────────────────────────────────


def find_identity_terms(text: str) -> list[str]:
    """Return any banned identity descriptors present in `text` (FR-010-05)."""
    low = text.lower()
    return [t for t in BANNED_IDENTITY_TERMS if t in low]


def find_explicit_terms(text: str) -> list[str]:
    """Return any explicit (F-014-only) terms present in `text` (NFR-010-07 SFW guard)."""
    low = text.lower()
    return [t for t in EXPLICIT_TERMS if t in low]


def assert_no_identity_terms(text: str) -> None:
    leaked = find_identity_terms(text)
    if leaked:
        raise ValueError(f"prompt restates identity (F-009 owns it): {leaked}")


def assert_sfw(text: str) -> None:
    leaked = find_explicit_terms(text)
    if leaked:
        raise ValueError(f"prompt leaked explicit vocabulary (F-014 owns it): {leaked}")


# ── prompt composition ───────────────────────────────────────────────────────────────────────────


def _pick_outfit(style: PersonaStyle, seed: int, shot_index: int) -> str:
    outfits = style.outfits or ("casual everyday outfit",)
    return outfits[(seed + shot_index) % len(outfits)]


def _scene_activity(slot: LifeSlot) -> str:
    act = slot.activity.strip()
    return act if act else "spending a quiet moment"


def _location_phrase(slot: LifeSlot, style: PersonaStyle, seed: int) -> str:
    loc = slot.location.strip()
    if loc:
        return loc
    if style.locations:
        return style.locations[seed % len(style.locations)]
    return ""


def author_prompt(
    slot: LifeSlot,
    style: PersonaStyle,
    framing: Framing,
    config: PromptAuthorConfig = DEFAULT_CONFIG,
    *,
    seed: int = 0,
    shot_index: int = 0,
) -> str:
    """Compose one structured, model-ready positive prompt (FR-010-02).

    Order: subject + scene/activity + location + outfit + framing/pose + time-of-day lighting + mood
    + phone-photo realism cues + aesthetic/palette. Identity is deliberately absent (F-009). The
    negative list is emitted separately onto `GenParams.negative` (see `author_jobs`)."""
    if slot.is_empty():
        slot = config.default_scene
    lighting = config.time_lighting.get(slot.time_of_day, config.time_lighting.get("", ""))
    parts = [
        config.subject_token,
        _scene_activity(slot),
        _location_phrase(slot, style, seed),
        _pick_outfit(style, seed, shot_index),
        framing.phrase,
        lighting,
        (f"{slot.mood.strip()} mood" if slot.mood.strip() else ""),
        *config.realism_cues,
        style.aesthetic,
        style.palette,
    ]
    prompt = ", ".join(p.strip() for p in parts if p and p.strip())
    # Belt-and-braces: authored text must never restate identity nor drift NSFW.
    assert_no_identity_terms(prompt)
    assert_sfw(prompt)
    return prompt


def _select_framings(config: PromptAuthorConfig, count: int, seed: int) -> list[Framing]:
    """Pick `count` framings deterministically, rotated by seed; distinct while count ≤ vocab size,
    wrapping with a variation suffix beyond that (FR-010-04 / NFR-010-03)."""
    vocab = config.framings
    n = len(vocab)
    offset = seed % n
    out: list[Framing] = []
    for i in range(count):
        base = vocab[(offset + i) % n]
        if i < n:
            out.append(base)
        else:
            lap = i // n
            out.append(replace(
                base,
                key=f"{base.key}_v{lap}",
                phrase=f"{base.phrase}, alternate take {lap}",
                pose=f"{base.pose} v{lap}",
            ))
    return out


def slot_signature(persona_slug: str, slot: LifeSlot, seed: int) -> str:
    """Short stable hash of (persona, slot, seed) for idempotent job keys (FR-010-08 provenance)."""
    raw = "|".join([persona_slug, slot.activity, slot.location, slot.mood, slot.time_of_day, str(seed)])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def author_jobs(
    persona_slug: str,
    slot: LifeSlot | None = None,
    style: PersonaStyle | None = None,
    config: PromptAuthorConfig = DEFAULT_CONFIG,
    *,
    count: int | None = None,
    base_seed: int = 0,
    job_key_prefix: str | None = None,
    references: list[str] | None = None,
) -> list[GenerationJob]:
    """Author a slot's shot set as F-008 `GenerationJob`s (FR-010-04/08/10/11).

    This is the entry point F-011 (daily batch) calls: it decides the persona, the slot (from F-006),
    the reference set (from F-009) and *how many* photos; F-010 turns that into ready-to-enqueue jobs.
    `references` (identity refs, F-009) are passed through untouched — F-010 never authors identity.
    Deterministic: same args (incl. `base_seed`) → identical prompts, seeds and job keys."""
    slot = slot if slot is not None and not slot.is_empty() else config.default_scene
    style = style if style is not None else config.style_for(persona_slug)
    n = count if count is not None else config.shot_count
    n = max(1, n)
    prefix = job_key_prefix or f"{persona_slug}:{slot_signature(persona_slug, slot, base_seed)}"
    negative = ", ".join(config.negatives)

    jobs: list[GenerationJob] = []
    for i, framing in enumerate(_select_framings(config, n, base_seed)):
        seed_i = base_seed + i
        prompt = author_prompt(slot, style, framing, config, seed=base_seed, shot_index=i)
        params = replace(config.params, seed=seed_i, negative=negative)
        meta = SlotMeta(
            pose=framing.pose,
            background=_location_phrase(slot, style, base_seed) or slot.activity,
            location=slot.location or _location_phrase(slot, style, base_seed),
            activity=slot.activity,
            time_of_day=slot.time_of_day,
        )
        jobs.append(GenerationJob(
            job_key=f"{prefix}#{i:02d}",
            persona_slug=persona_slug,
            prompt=prompt,
            references=list(references or []),
            params=params,
            slot=meta,
        ))
    return jobs
