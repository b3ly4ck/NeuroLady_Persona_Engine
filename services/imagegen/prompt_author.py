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
# FR-010-13: the directive's wording is F-009's; F-010 only places it at the prompt opening.
from services.imagegen.identity import preservation_directive

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
# FR-010-14 Composition: ONLY two kinds of POV exist in a real camera roll — she took the photo
# herself, or someone she is with took it. Nothing tripod-ish, nothing editorial.
DEFAULT_FRAMINGS: tuple[Framing, ...] = (
    Framing("selfie_closeup",
            "she is taking a selfie herself, phone in her outstretched hand, front camera at "
            "arm's length, her arm visible at the edge of the frame, slightly awkward close angle",
            "close selfie"),
    Framing("companion_across",
            "photo taken by a companion sitting across from her, casual eye-level snapshot, "
            "she is aware of the camera and relaxed, framing slightly off-center",
            "companion shot"),
    Framing("candid_moment",
            "candid photo a friend took of her mid-moment, she is not posing, caught naturally "
            "in the middle of what she is doing, imperfect timing",
            "candid moment"),
    Framing("mirror_fulllength",
            "mirror selfie, she is holding the phone which is visible in the reflection, "
            "full-length framing, casual stance",
            "mirror selfie"),
    Framing("selfie_high_angle",
            "selfie taken by herself from slightly above, front camera angled down, her arm "
            "raised holding the phone, casual tilt to the frame",
            "high-angle selfie"),
    Framing("companion_steps_away",
            "photo taken by a friend from a few steps away, ordinary standing snapshot, whole "
            "scene visible around her, phone-camera perspective",
            "friend snapshot"),
    Framing("selfie_walking",
            "walking selfie, she holds the phone in front of her while moving, slight motion in "
            "the frame, spontaneous",
            "walking selfie"),
    Framing("companion_table",
            "snapshot taken by the person she is with, from just across the table, casual and "
            "close, everyday framing with the table edge in the shot",
            "table snapshot"),
)


# ── vocabularies (config-driven — NFR-010-04) ────────────────────────────────────────────────────

# The iPhone hyperrealism block (FR-010-14): labeled sections with CONCRETE physical detail —
# the difference between "rendered" and "shot". Wording avoids every banned identity substring
# (no "face"/"eyes"/"nose"/"skin tone" — the guard is substring-based).
REALISM_SKIN_DETAIL: str = (
    "Skin and detail: visible skin pores, natural skin texture, a few minor skin blemishes, "
    "slight oily sheen on the T-zone, a couple of stray hairs out of place, slightly flushed "
    "cheeks, natural asymmetry, no makeup airbrushing"
)
REALISM_CAMERA_SIGNATURE: str = (
    "Camera signature: shot on an iPhone, handheld, slight motion softness, mild sensor noise in "
    "the shadows, smartphone dynamic range with slightly blown-out highlights, everything mostly "
    "in focus with minimal depth-of-field falloff, tiny lens smudge glare"
)
REALISM_PROCESSING: str = (
    "Processing: completely unedited, straight off the camera roll, no retouching, no beauty "
    "filter, no smoothing, natural color response, tiny white-balance drift, ordinary JPEG "
    "compression from the phone"
)
REALISM_PHOTO_TYPE: str = (
    "Photo type: amateur unedited iPhone photo from a real person's camera roll, casual and "
    "unposed, ordinary everyday snapshot"
)

# Kept as a tuple for config compatibility (from_dict overrides) — joined into the Realism
# sections in author_prompt.
DEFAULT_REALISM_CUES: tuple[str, ...] = (
    REALISM_SKIN_DETAIL,
    REALISM_CAMERA_SIGNATURE,
    REALISM_PROCESSING,
)

# FR-010-15: negatives target the STUDIO look — never natural phone artifacts (no bare "blurry",
# no "lowres": those would fight sensor noise / motion softness we explicitly ask for).
DEFAULT_NEGATIVES: tuple[str, ...] = (
    "studio lighting", "softbox lighting", "professional photoshoot", "editorial photo",
    "magazine cover", "posed fashion model", "retouched skin", "airbrushed skin",
    "beauty filter", "flawless glossy skin", "porcelain skin", "cinematic color grading",
    "dramatic rim lighting", "DSLR bokeh portrait", "shallow depth of field",
    "oversharpened", "HDR look",
    "watermark", "text", "logo", "signature",
    "extra limbs", "extra fingers", "deformed hands", "disfigured",
    "cartoon", "anime", "3d render", "cgi", "doll-like",
    # FR-010-18: multi-anchor conditioning produced frames with the subject rendered twice.
    "two people", "duplicate person", "multiple women", "same person twice", "cloned figure",
    "second person in background",
)

# Time-of-day → REALISTIC imperfect light (FR-010-07 + FR-010-14): how phones actually see the
# world, not how ad campaigns light it. No "golden hour", no "cinematic".
DEFAULT_TIME_LIGHTING: dict[str, str] = {
    "morning": "flat soft morning light, slightly overexposed sky, pale colors",
    "afternoon": "harsh direct midday light with real hard shadows, slightly squinting brightness",
    "evening": "mixed warm indoor lamp light, slightly underexposed, uneven light across the frame",
    "night": "night time, dim indoor lighting, visible noise in the dark areas, warm artificial"
             " light, dark window reflections",
    "": "plain unremarkable daylight, neutral and a little flat",
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
    # Empty → the FR-010-14 "Photo type" opening (amateur unedited iPhone photo). A subject like
    # the old "candid photo of a woman" is a DEFECT: it unbinds the output from the reference.
    subject_token: str = ""
    realism_cues: tuple[str, ...] = DEFAULT_REALISM_CUES
    negatives: tuple[str, ...] = DEFAULT_NEGATIVES
    framings: tuple[Framing, ...] = DEFAULT_FRAMINGS
    time_lighting: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TIME_LIGHTING))
    default_scene: LifeSlot = DEFAULT_SCENE
    default_style: PersonaStyle = field(default_factory=PersonaStyle)
    styles: dict[str, PersonaStyle] = field(default_factory=dict)   # per persona_slug
    # FR-010-16: quality budget ≤ ~2 min/photo → 8 distilled steps at 1024² by default.
    params: GenParams = field(default_factory=lambda: GenParams(steps=8))

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
    """Compose one large, fully-structured, model-ready positive prompt (FR-010-02 / FR-010-14).

    Labeled sections (Photo type → Scene → Composition → Outfit → Lighting → Skin/Camera/Processing
    realism blocks) — the "shot, not rendered" contract of §FR-010-14. Identity is deliberately
    absent (F-009 owns it; the preservation directive is prepended in `author_jobs`). The negative
    list is emitted separately onto `GenParams.negative`."""
    if slot.is_empty():
        slot = config.default_scene
    lighting = config.time_lighting.get(slot.time_of_day, config.time_lighting.get("", ""))
    mood = f", {slot.mood.strip()} mood" if slot.mood.strip() else ""
    style_tail = ", ".join(p for p in (style.aesthetic, style.palette) if p and p.strip())
    sections = [
        config.subject_token or REALISM_PHOTO_TYPE,
        # FR-010-19 (ISS-008): the surrounding objects are named IN THE PROMPT, so the frame really
        # contains them — the same list is what she is given to describe afterwards. Describing
        # objects that were never requested would just move the confabulation into our own code.
        f"Scene: {_scene_activity(slot)}, {_location_phrase(slot, style, seed)}"
        f", with {scene_objects(slot.location, 'en')} visible around her"
        f"{mood}".rstrip(", "),
        f"Composition: {framing.phrase}",
        # FR-010-17: wardrobe is authored HERE and is authoritative — the reference pictures'
        # clothing must not carry over (the body anchor's outfit leaked into every scene).
        f"Outfit: she is wearing {_pick_outfit(style, seed, shot_index)}, "
        f"not the clothing from the reference pictures",
        f"Lighting: {lighting}",
        *config.realism_cues,
    ]
    if style_tail:
        sections.append(f"Style: {style_tail}")
    prompt = ". ".join(s.strip().rstrip(".") for s in sections if s and s.strip()) + "."
    # Belt-and-braces: authored text must never restate identity nor drift NSFW.
    assert_no_identity_terms(prompt)
    assert_sfw(prompt)
    return prompt


# ── scene description (FR-010-19/20/21, ISS-008) ────────────────────────────────────────────────
#
# The five slot fields describe the generation REQUEST ("background: home", "pose: high-angle
# selfie"). When she is later asked "а что у тебя на фоне?" that is useless — measured live, she
# could say where she was but not what was behind her. This authors, from the same slot the prompt
# is built from, ONE plain sentence naming what is visible, IN HER LANGUAGE, in words a person would
# use. It never contains framing jargon and is never the technical prompt.

# Concrete things that plausibly surround her, per location. Keyed by the location token F-010
# already derives; "" is the safe default.
SCENE_OBJECTS: dict[str, dict[str, str]] = {
    "home": {
        "ru": "диван, торшер, включённый телевизор и плед",
        "en": "the sofa, a floor lamp, the TV on and a blanket",
    },
    "cafe": {
        "ru": "деревянный столик, чашка кофе, окно и другие посетители",
        "en": "a wooden table, a coffee cup, the window and other customers",
    },
    "outdoors": {
        "ru": "деревья, дорожка парка и трава",
        "en": "trees, the park path and grass",
    },
    "gym": {
        "ru": "тренажёры, зеркальная стена и коврик",
        "en": "the machines, the mirrored wall and a mat",
    },
    "office": {
        "ru": "рабочий стол, ноутбук, кружка и жалюзи на окне",
        "en": "a desk, a laptop, a mug and window blinds",
    },
    "restaurant": {
        "ru": "накрытый стол, бокалы, свеча и приглушённый зал",
        "en": "a laid table, glasses, a candle and the dim dining room",
    },
    "": {"ru": "обычная домашняя обстановка", "en": "an ordinary everyday setting"},
}

SCENE_LIGHT: dict[str, dict[str, str]] = {
    "morning": {"ru": "утренний свет из окна", "en": "morning light from the window"},
    "afternoon": {"ru": "яркий дневной свет", "en": "bright daylight"},
    "evening": {"ru": "тёплый вечерний свет ламп", "en": "warm evening lamplight"},
    "night": {"ru": "приглушённый ночной свет", "en": "dim night lighting"},
    "": {"ru": "обычный дневной свет", "en": "ordinary daylight"},
}

_SCENE_TEMPLATE = {
    "ru": "{activity}; вокруг {objects}; {light}",
    "en": "{activity}; around her {objects}; {light}",
}


def scene_objects(location: str, language: str) -> str:
    """The concrete things surrounding her at `location`, in `language` (FR-010-19).

    Shared by the prompt (so they are rendered) and the description (so she can name them) — the
    single source that keeps what she says and what he sees the same thing."""
    lang = language if language in ("ru", "en") else "en"
    key = (location or "").strip().lower()
    return SCENE_OBJECTS.get(key, SCENE_OBJECTS[""])[lang]


def author_scene_description(slot: LifeSlot, language: str = "en",
                             config: PromptAuthorConfig = DEFAULT_CONFIG) -> str:
    """One human sentence describing what is visible in the frame (FR-010-19/20/21).

    Authored from the same slot as the prompt, so it costs nothing extra. Written in the persona's
    language because SHE speaks it later (F-002 context, F-012 captions). Contains no framing or
    technical vocabulary, and never describes her appearance (FR-010-05 still applies).
    """
    lang = language if language in ("ru", "en") else "en"
    if slot is None or slot.is_empty():
        slot = config.default_scene
    activity = (slot.activity or "").strip() or (
        "обычный момент дня" if lang == "ru" else "an ordinary moment")
    loc_key = (slot.location or "").strip().lower()
    objects = scene_objects(loc_key, lang)
    light = SCENE_LIGHT.get((slot.time_of_day or "").strip().lower(), SCENE_LIGHT[""])[lang]
    return _SCENE_TEMPLATE[lang].format(activity=activity, objects=objects, light=light)


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
    # keyword-only: the positional slots are a published API (F-011 and the tests call them
    # positionally), so a new parameter must never shift `style` out from under a caller.
    language: str = "en",
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

    # FR-010-12: every prompt OPENS with F-009's identity-preservation directive, bound to the
    # anchors actually supplied (Picture 1 = face, Picture 2 = body). Without it the model reads a
    # generic subject and drifts off the reference (architecture.md §4.3b).
    directive = preservation_directive(len(references or []))

    jobs: list[GenerationJob] = []
    for i, framing in enumerate(_select_framings(config, n, base_seed)):
        seed_i = base_seed + i
        scene = author_prompt(slot, style, framing, config, seed=base_seed, shot_index=i)
        prompt = f"{directive}{scene}" if directive else scene
        params = replace(config.params, seed=seed_i, negative=negative)
        meta = SlotMeta(
            # FR-010-19 (ISS-008): what is VISIBLE in the frame, in her language — the answer to
            # "а что у тебя на фоне?". The other fields describe the generation request.
            scene_description=author_scene_description(slot, language, config),
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
