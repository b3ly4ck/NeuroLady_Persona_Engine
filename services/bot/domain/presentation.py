"""F-013 Dynamic Persona Presentation — the live, time/context-aware selection greeting.

The **first impression** when a persona is opened (architecture.md §1, post-selection step of the
F-001 flow). Instead of a static bio card, F-013 composes **one** greeting message *in her voice*
that reflects **what she's doing right now** (her current F-006 Life Engine slot) and **the local
time of day**, paired with a **fresh, fitting photo** picked from today's F-011 archive via
F-012-style tag matching. It is a pure lookup + template compose — **no** hot-path generation
(FR-013-07 / NFR-013-01), and it **never** returns an intimate asset at the entry moment
(FR-013-06 / NFR-013-08).

Scope boundary (feature §Scope): F-013 produces only the *content* (greeting text + chosen photo).
Gallery rendering, selection UX, screen order and the actual outbound send stay in F-001
(FR-013-10); after the greeting, normal chat is F-002/F-003 (FR-013-11).

Everything here is deterministic given a `seed`, so variety across opens (FR-013-04 / NFR-013-02)
is testable: different time/slot → different card; same slot, different seed → varied phrasing.
Greeting voice/tone is driven by the persona's `comm_settings_json` (F-003 register/emoji/slang),
so tuning tone needs no code change (FR-013-09 / NFR-013-07).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain.humanize import CommSettings, parse_settings
from services.bot.models import MediaAsset, MediaKind, Persona

# ── time-of-day buckets ─────────────────────────────────────────────────────────────────────────

# Coarse period used for photo tag matching (mirrors the F-010/F-011 `time_of_day` slot values).
PHOTO_PERIODS = ("morning", "afternoon", "evening", "night")

# Fine narrative period driving the greeting phrasing (finer than the photo tag so "just woke up"
# reads differently from "late but still up").
NARRATIVE_PERIODS = (
    "early_morning", "morning", "midday", "afternoon", "evening", "night", "late_night",
)


def photo_period(hour: int) -> str:
    """Coarse time-of-day bucket used to match an archive photo's `time_of_day` tag (FR-013-02)."""
    if 5 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 16:
        return "afternoon"
    if 17 <= hour <= 21:
        return "evening"
    return "night"


def narrative_period(hour: int) -> str:
    """Fine time-of-day bucket that flavors the greeting text (FR-013-01)."""
    if 5 <= hour <= 8:
        return "early_morning"
    if 9 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 14:
        return "midday"
    if 15 <= hour <= 17:
        return "afternoon"
    if 18 <= hour <= 21:
        return "evening"
    if 22 <= hour <= 23:
        return "night"
    return "late_night"  # 0..4


# Fine narrative period -> coarse photo period (so the greeting's moment and the photo agree).
_NARRATIVE_TO_PHOTO = {
    "early_morning": "morning",
    "morning": "morning",
    "midday": "afternoon",
    "afternoon": "afternoon",
    "evening": "evening",
    "night": "night",
    "late_night": "night",
}

_PERIOD_EMOJI = {
    "early_morning": "☀️",
    "morning": "🌞",
    "midday": "☕",
    "afternoon": "🙂",
    "evening": "🌆",
    "night": "🌙",
    "late_night": "🌙",
}


# ── greeting templates (config-driven; tunable without code — FR-013-09 / NFR-013-07) ─────────────

# [language][narrative_period] -> list of opener variants. Each opener names her (natural for a
# first text and keeps the F-001 linkage: the opener belongs to the selected persona).
_OPENERS: dict[str, dict[str, list[str]]] = {
    "en": {
        "early_morning": ["hey, it's {name}… just dragged myself out of bed",
                          "morning — {name} here, barely awake yet"],
        "morning": ["hey it's {name}, morning's just getting going",
                    "morning! {name} here, easing into the day"],
        "midday": ["hey, {name} here — finally a little break",
                   "ugh finally a breather, it's {name}"],
        "afternoon": ["hey it's {name}, afternoon's flying by",
                      "{name} here, right in the middle of the afternoon"],
        "evening": ["hey it's {name}, winding down my evening",
                    "evening — {name} here, finally slowing down"],
        "night": ["hey, it's {name}… getting late over here",
                  "{name} here, it's late but i'm still up"],
        "late_night": ["hey it's {name}, can't sleep",
                       "{name} here… way too late to be up"],
    },
    "ru": {
        "early_morning": ["привет, это {name}… только вылезла из кровати",
                         "утро — {name}, ещё толком не проснулась"],
        "morning": ["привет, это {name}, утро только начинается",
                    "доброе утро! это {name}"],
        "midday": ["привет, это {name} — наконец-то передышка",
                   "уф, наконец перерыв, это {name}"],
        "afternoon": ["привет, это {name}, день в разгаре",
                      "{name} на связи, уже вторая половина дня"],
        "evening": ["привет, это {name}, потихоньку расслабляюсь",
                    "вечер — {name}, наконец сбавляю темп"],
        "night": ["привет, это {name}… уже поздно",
                  "{name} тут, поздно, но я ещё не сплю"],
        "late_night": ["привет, это {name}, не спится",
                       "{name}… совсем поздно, а я не сплю"],
    },
}

# [language][tone] -> question variants. Tone is derived from the persona's comm settings, so a shy
# (gentle) persona and a bubbly (bold/slangy) one read differently (FR-013-09).
_QUESTIONS: dict[str, dict[str, list[str]]] = {
    "en": {
        "soft": ["how are you?", "how's your day been?"],
        "warm": ["what's up?", "how's your day?"],
        "peppy": ["what's good?", "what are you up to?"],
    },
    "ru": {
        "soft": ["как ты?", "как проходит день?"],
        "warm": ["что делаешь?", "как день?"],
        "peppy": ["чем занят?", "ну рассказывай, как ты?"],
    },
}

# Trailing clause weaving in her current activity, so greeting + photo narrate the same moment.
_ACTIVITY_CONNECTOR = {"en": " — {activity} rn.", "ru": " — сейчас {activity}."}

_EMOJI_THRESHOLD = 0.35  # append the period emoji only for personas that use emoji at all


def _tone(settings: CommSettings) -> str:
    """Map the persona's F-003 comm settings to a greeting tone tier (FR-013-09)."""
    if settings.register == "gentle":
        return "soft"
    if settings.slang_level >= 0.6 or settings.emoji_frequency >= 0.6:
        return "peppy"
    return "warm"


def _lang(persona: Persona) -> str:
    return persona.language if persona.language in _OPENERS else "en"


_LANG_NAMES = {"ru": "Russian", "en": "English"}


def _opener_instruction(
    persona: Persona, kind: str, *, activity: str | None, period: str, stage: str | None,
) -> str:
    """The system instruction that makes the model WRITE the opener (FR-013-13/15).

    Compact on purpose — it is prepended to the persona's own recent conversation on the resume
    path, so she can ground "на чём мы остановились?" in what they were actually saying rather than
    a generic line. No F-020 media-intent instruction is added here (a greeting never requests
    media), and the shape is pinned to ONE short message in her language (FR-013-15).
    """
    lang = _LANG_NAMES.get(_lang(persona), "English")
    moment = f"It is {period.replace('_', ' ')}."
    if activity:
        moment += f" Right now you are: {activity.strip().rstrip('.')}."
    if stage:
        moment += f" Your bond with him is at the '{stage}' stage."
    if kind == "resume":
        task = (
            "He is RE-OPENING a chat the two of you already had going — you are NOT meeting for the "
            "first time. Greet him back warmly, in your own voice, as someone who remembers him and "
            "the conversation above. If there is a clear thread to pick back up, nod to it naturally; "
            "otherwise just welcome him back. Do NOT re-introduce yourself."
        )
    else:
        task = (
            "He has just picked you and opened your chat for the first time in this moment. Greet him "
            "in your own voice and make him feel you are a real person living this exact moment."
        )
    return (
        f"You are {persona.name}. {moment} {task}\n"
        f"Write ONE short opener message ({lang}), one or two sentences, in your natural texting "
        f"style with your usual emoji. Output ONLY the message text — no quotes, no narration, no "
        f"labels, nothing else."
    )


async def compose_opener(
    persona: Persona,
    *,
    kind: str,
    chat_client,
    fallback: str,
    activity: str | None = None,
    now_local: datetime | None = None,
    recent: "list | None" = None,
    stage: str | None = None,
) -> str:
    """LLM-compose ONE fresh opener in her voice, or return `fallback` (FR-013-13/14/15, ISS-012).

    `kind` is "selection" (first open) or "resume" (re-entering an active chat). `recent` is the
    session's recent messages (resume only) so she can reference where they left off. ANY failure —
    model down, exception, empty output — returns `fallback` (the F-013 template or the static
    resume line), so the entry moment is never silent and never an error (FR-013-14). Whatever the
    model returns is post-processed like a normal turn: a stray F-020 signal is stripped
    (FR-020-04), so the sentinel can never leak into the greeting.
    """
    from services.bot.domain.life_engine import local_now  # noqa: F401 - kept for callers' parity
    from services.bot.domain.media_intent import strip_signal
    from services.bot.domain.messages import to_openai_messages

    period = narrative_period((now_local or datetime.now(timezone.utc)).hour)
    system = _opener_instruction(persona, kind, activity=activity, period=period, stage=stage)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if recent:
        # Prior turns give her the thread to pick back up. `to_openai_messages` maps stored
        # Message rows to role/content; a plain list of dicts is passed through untouched.
        try:
            messages.extend(
                recent if recent and isinstance(recent[0], dict) else to_openai_messages(recent)
            )
        except Exception:  # malformed history must never sink the greeting
            pass
    # A final nudge so the model produces the opener, not a continuation of the last user line.
    messages.append({"role": "user", "content": "[he just opened the chat — greet him]"})

    try:
        if not await chat_client.is_ready():
            return fallback
        raw = await chat_client.complete(messages, temperature=0.9, max_tokens=200)
    except Exception:
        return fallback
    text = strip_signal(raw or "").strip().strip('"').strip()
    return text or fallback


def compose_greeting(
    persona: Persona,
    activity: str | None,
    now_local: datetime,
    *,
    settings: CommSettings | None = None,
    seed: int | None = None,
) -> str:
    """Compose ONE time/activity-aware greeting in her voice (FR-013-01/03/09).

    Deterministic given `seed`; a `None` seed draws fresh entropy so repeated opens vary
    (FR-013-04 / NFR-013-02). `activity` is her current F-006 slot text (or None if she has no plan
    yet — the greeting then degrades to a time-only opener, never an error, FR-013-08).
    """
    settings = settings or parse_settings(persona)
    lang = _lang(persona)
    period = narrative_period(now_local.hour)
    rng = random.Random(seed)

    opener = rng.choice(_OPENERS[lang][period]).format(name=persona.name)
    question = rng.choice(_QUESTIONS[lang][_tone(settings)])

    text = opener
    if activity:
        text += _ACTIVITY_CONNECTOR[lang].format(activity=activity.strip().rstrip("."))
    elif not text.endswith((".", "…", "!")):
        text += "."
    text += f" {question}"

    if settings.emoji_frequency >= _EMOJI_THRESHOLD:
        text += f" {_PERIOD_EMOJI[period]}"
    return text


# ── welcome photo selection (F-012-style tag matching over the F-011 archive) ─────────────────────


def is_sfw(asset: MediaAsset) -> bool:
    """The welcome photo is ALWAYS SFW — never an intimate asset at the entry moment
    (FR-013-06 / NFR-013-08)."""
    return not asset.intimate and asset.intimacy_level <= 0


def resolve_asset_path(media_root: str | Path, storage_ref: str) -> str:
    """Resolve a MEDIA_ASSET.storage_ref (`media/<slug>/photos/<id>.png`) to a filesystem path
    under `media_root` (which IS the `media/` dir — same convention as imagegen.store.reconcile)."""
    return str(Path(media_root) / storage_ref.removeprefix("media/"))


def _score_asset(asset: MediaAsset, coarse: str, narrative: str, activity: str | None) -> int:
    """How well an archive asset matches the narrated moment (higher = better) — F-012-style tag
    matching on `time_of_day` + `activity` (FR-013-02 / FR-013-05)."""
    from services.imagegen.store import parse_meta

    meta = parse_meta(asset)
    tod = str(meta.get("time_of_day", "")).lower()
    act = str(meta.get("activity", "")).lower()
    score = 0
    if tod:
        if tod in (coarse, narrative):
            score += 3
        elif coarse in tod or narrative in tod:
            score += 2
    if activity and act:
        words = {w for w in activity.lower().split() if len(w) > 3}
        if words & set(act.split()):
            score += 2
    return score


def select_welcome_photo(
    assets: list[MediaAsset],
    now_local: datetime,
    activity: str | None,
    media_root: str | Path,
    *,
    seed: int | None = None,
) -> tuple[MediaAsset | None, str | None]:
    """Pick the SFW, context-matching welcome photo from the day's archive (FR-013-02/05/06).

    SFW assets only (intimate excluded, NFR-013-08). Best tag-match wins; on a tie a `seed`-driven
    choice keeps the welcome fresh across opens (FR-013-04). Returns `(None, None)` when the archive
    has no usable SFW photo — the caller then degrades to a text-only greeting (FR-013-08).
    """
    candidates = [a for a in assets if is_sfw(a) and a.kind == MediaKind.photo]
    if not candidates:
        return None, None
    coarse = photo_period(now_local.hour)
    narrative = narrative_period(now_local.hour)
    scored = {a.id: _score_asset(a, coarse, narrative, activity) for a in candidates}
    best = max(scored.values())
    top = sorted((a for a in candidates if scored[a.id] == best), key=lambda a: a.id)
    chosen = random.Random(seed).choice(top)
    return chosen, resolve_asset_path(media_root, chosen.storage_ref)


# ── the composed card (content only — the handler owns the single outbound send) ──────────────────


@dataclass
class PresentationCard:
    """The content of the selection-moment greeting (FR-013-03/10).

    `photo_ref` is a resolved filesystem path (or None → text-only). `text` is the one greeting
    message. The handler sends exactly ONE outbound message carrying `text` (+ photo, + keyboard);
    F-013 never sends and never builds navigation (FR-013-10).
    """
    text: str
    photo_ref: str | None
    asset_id: str | None


def _default_media_root() -> str:
    from services.imagegen.config import ImageRunnerSettings

    return ImageRunnerSettings().media_root


async def compose_presentation(
    db: AsyncSession,
    persona: Persona,
    *,
    media_root: str | Path | None = None,
    now: datetime | None = None,
    seed: int | None = None,
    chat_client=None,
) -> PresentationCard:
    """Compose the full live greeting card for a just-opened persona (FR-013-01/02/03/07/08).

    Reads her current F-006 activity and today's F-011 archive, then composes the greeting text and
    picks a fitting SFW photo. When `chat_client` is provided the greeting is **LLM-composed in her
    voice** (FR-013-13); without it (or on model failure) it falls back to the template greeting.
    **No** image generation is ever triggered (FR-013-07 / NFR-013-01), and it degrades gracefully to
    a text-only greeting when the archive is empty (FR-013-08 / NFR-013-06).
    """
    from services.bot.domain.life_engine import local_now
    from services.bot.domain.life_engine_store import get_current_activity
    from services.imagegen.store import latest_available_assets

    media_root = media_root if media_root is not None else _default_media_root()
    now_utc = now or datetime.now(timezone.utc)
    now_local = local_now(persona.timezone, now_utc)

    activity = await get_current_activity(db, persona.id, persona.timezone)
    template = compose_greeting(persona, activity, now_local, seed=seed)
    if chat_client is not None:
        text = await compose_opener(
            persona, kind="selection", chat_client=chat_client, fallback=template,
            activity=activity, now_local=now_local,
        )
    else:
        text = template

    assets = await latest_available_assets(db, persona.id, now_utc)
    chosen, photo_ref = select_welcome_photo(assets, now_local, activity, media_root, seed=seed)
    asset_id = chosen.id if chosen is not None else None
    return PresentationCard(text=text, photo_ref=photo_ref, asset_id=asset_id)
