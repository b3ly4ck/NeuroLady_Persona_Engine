"""F-012 On-Demand Photo Delivery — select-and-send an SFW photo into the live chat.

This is the **consumer** side of the day archive (F-008/F-011 fill it; F-012 serves it). On an SFW
photo request — or a proactive share — it picks the **best-matching, already-generated, unsent**
asset from today's archive (degrading to the most recent prior day via
`store.latest_available_assets`), matched to the **current moment** (time-of-day / activity /
location / mood carried in a context dict, sourced from F-006 upstream), marks it sent so it is
**never repeated** to that user (`MediaSend`), requests a one-line caption **in her voice** via the
chat client (F-002/F-003), and hands back a result for the caller to deliver through the §3.6 Media
path. It **never generates on the reply hot path** — pure lookup + send (FR-012-04 / NFR-012-01).

The result carries the delivered asset's **scene metadata** (background / location / activity / pose
/ time-of-day) and `recent_sends()` serves the same descriptors for the last few photos this user
received — the §2/§3.6/§4.2 "media **plus its metadata**" contract, so the Orchestrator can put
**what she actually sent** into her context instead of letting her invent a scene
(FR-012-14/15, NFR-012-09; ISS-006).

Boundaries (feature scope note): intimate requests are **classified and routed to F-014's gate**
(`IntimacyGate` protocol below), never served from the SFW archive (FR-012-07 / NFR-012-08);
relationship stage (F-005) only **paces** sharing (FR-012-06); it does not author persona voice
(the caption/deflection text comes from the chat client). Everything tunable is in
`MediaDeliveryConfig` (FR-012-11 / NFR-012-07); the logic is deterministic and per-user isolated
(NFR-012-06).
"""
from __future__ import annotations

import logging

from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain.relationship import STAGES, stage_index
from services.bot.models import MediaAsset, MediaSend, Persona, Relationship
from services.imagegen.store import parse_meta, retained_assets


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── configuration (FR-012-11 / NFR-012-07: weighting + caps tunable, no code change) ─────────────


@dataclass(frozen=True)
class MediaDeliveryConfig:
    """All F-012 tunables — match weighting, closest-slot ladder, per-stage caps, proactive knobs."""

    # Per meta-tag match weights (contribution to an asset's context-fit score).
    weight_time_of_day: float = 3.0
    weight_activity: float = 4.0
    weight_location: float = 2.0
    weight_mood: float = 1.0
    # Time-of-day ladder for the closest-slot fallback (FR-012-03). Cyclic: night is adjacent to
    # morning. A non-exact slot scores weight_time_of_day minus (cyclic distance * penalty).
    time_slots: tuple[str, ...] = ("morning", "afternoon", "evening", "night")
    slot_adjacency_penalty: float = 1.0
    # Per-stage frequency caps: max photos per rolling window (FR-012-06 / NFR-012-04). A brand-new
    # user is limited; a bonded user shares far more freely. Unknown stage → the Stranger cap.
    stage_caps: dict[str, int] = field(default_factory=lambda: {
        "Stranger": 1,
        "Acquaintance": 2,
        "Friend": 4,
        "Flirting": 6,
        "Romance": 10,
        "Love": 15,
        "Devoted": 25,
    })
    pacing_window_hours: float = 24.0
    # Proactive share (FR-012-09): she only volunteers a photo once she's at least this bonded and
    # only when the moment genuinely fits (score at/above the floor).
    proactive_stage_floor: str = "Friend"
    proactive_min_score: float = 4.0
    # Recent-sends lookup feeding the conversation context (FR-012-15 / F-002 FR-002-25/26, ISS-006).
    # Bounded on purpose: the block must never grow the prompt without limit.
    context_recent_sends: int = 3
    context_recency_hours: float = 48.0
    # F-021 freshness: a RANKING signal, not a filter (FR-021-02). `freshness_bonus` is the value
    # a frame from today carries; it decays **proportionally** with age (`bonus / (1 + age*decay)`).
    # Proportional and not linear on purpose: FR-021-02 promises that a *large bonus* degenerates to
    # "today only in practice", and with a linear `bonus - age*decay` it never can — the gap between
    # two ages would be `age*decay` no matter how large the bonus is, so the knob would silently do
    # nothing. Near-zero bonus ⇒ variety-first. Never negative: age never actively penalises.
    # D7: the margin an older frame must beat IS the freshness it forfeits — one scale, no second knob.
    freshness_bonus: float = 3.0
    freshness_decay_per_day: float = 1.0


DEFAULT_CONFIG = MediaDeliveryConfig()


# ── request classification + intimate routing (FR-012-07 / NFR-012-08) ───────────────────────────


class PhotoRequestClass(str, Enum):
    """How a photo request classifies for routing."""

    sfw = "sfw"                # clearly a normal photo → serve from the SFW archive
    intimate = "intimate"      # explicitly intimate → hand to F-014's gate
    ambiguous = "ambiguous"    # unclear/intimacy-adjacent → hand to the gate (safe side)


# Explicit intimate terms → always the gate.
# FR-012-17 (ISS-009): these lists are the FALLBACK behind F-020's model signal, so they must cover
# every language a deployed persona speaks. They were English-only while the live persona was
# Russian — "скинь голое фото" classified as SFW, i.e. the safety net never fired in the language
# the bot actually speaks. Russian entries are stored as **stems** (matched as substrings) so the
# inflected forms — голое / голую / голой / голышом — all hit one entry.
_INTIMATE_TERMS = (
    # English
    "nude", "naked", "sexy", "sext", "topless", "lingerie", "underwear", "boobs", "tits",
    "ass", "pussy", "nsfw", "porn", "strip", "explicit", "horny", "turn me on", "for my eyes",
    # Russian (stems)
    # Stems are chosen to avoid innocent collisions: "соск" would match "соскучился" and "попу"
    # would match "попугай", so both are spelled out instead.
    "голое", "голую", "голая", "голой", "голым", "голыш", "обнаж", "интимн", "эротич",
    "без одежды", "без трусов", "нижнем бель", "нижнее бель", "грудь", "сиськ", "соски",
    "попка", "попки", "задниц", "порно", "секс", "трахн", "возбуд", "разденьс",
    "откровенн", "ню фото", "нюдес", "нюдс",
)
# Intimacy-adjacent but unclear → the gate decides (never leak an intimate asset — NFR-012-08).
_AMBIGUOUS_TERMS = (
    # English
    "hotter", "spicy", "spicier", "tease", "teasing", "more skin", "show me more", "sultry",
    "naughty", "something more", "reveal", "flirty pic",
    # Russian (stems)
    "погорячее", "по-горячее", "пикантн", "дразн", "соблазн", "поменьше одежды", "посмелее",
    "что-нибудь такое", "что нибудь такое", "чувственн", "манящ",
)


def classify_photo_request(text: str) -> PhotoRequestClass:
    """SFW vs intimate vs ambiguous. Ambiguity resolves to the **gate-routed** side (NFR-012-08):
    an unclear request is never served from the SFW archive, so an intimate asset can never leak."""
    t = (text or "").lower()
    if any(term in t for term in _INTIMATE_TERMS):
        return PhotoRequestClass.intimate
    if any(term in t for term in _AMBIGUOUS_TERMS):
        return PhotoRequestClass.ambiguous
    return PhotoRequestClass.sfw


def routes_to_gate(kind: PhotoRequestClass) -> bool:
    """True for everything except a clearly-SFW request (FR-012-07 / NFR-012-08)."""
    return kind is not PhotoRequestClass.sfw


# Photo-request INTENT detection (integration wiring): is this chat message asking for a photo at
# all? Only then does the delivery path run; everything else stays a normal F-002 turn. RU + EN,
# deliberately conservative — a false negative costs a photo, a false positive hijacks a turn.
_PHOTO_NOUNS = (
    "фото", "фотку", "фотка", "фотографи", "селфи", "фотки", "пикчу",
    "photo", " pic ", " pic?", " pic!", "a pic", "picture", "selfie", " snap",
)
_PHOTO_VERBS = (
    "пришли", "скинь", "отправь", "покажи", "сфоткай", "шли", "хочу увидеть", "можно",
    "send", "show", "share", "take", "got a", "can i see", "let me see", "wanna see",
)


def looks_like_photo_request(text: str) -> bool:
    """True when the message asks for a photo (verb+noun pair, or an intimate ask that names
    imagery). Intent only — SFW/intimate classification stays `classify_photo_request`."""
    t = f" {(text or '').lower().strip()} "
    has_noun = any(n in t for n in _PHOTO_NOUNS)
    if not has_noun:
        return False
    if any(v in t for v in _PHOTO_VERBS):
        return True
    # an explicitly intimate ask that names a photo counts even without a request verb
    return classify_photo_request(t) is not PhotoRequestClass.sfw


class IntimacyGate(Protocol):
    """F-014's intimate-photo gate (built in parallel). F-012 only **routes** to it — it owns none
    of the gating/consent/delivery logic. The gate decides entitlement/consent and returns its own
    result object, which F-012 passes back unchanged in `DeliveryResult.gate_result`."""

    async def handle_intimate_request(
        self,
        *,
        user_id: int,
        persona_id: int,
        stage: str,
        request_text: str,
        context: dict,
    ) -> Any:
        ...


class CaptionClient(Protocol):
    """The chat-LLM interface used to author caption/deflection text in her voice (F-002/F-003).

    `services.bot.chat_client.ChatClient` satisfies this directly; tests inject a fake. F-012 never
    writes persona voice itself — it only assembles the request and calls `complete`."""

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        ...


# ── current-moment context ───────────────────────────────────────────────────────────────────────


@dataclass
class PhotoContext:
    """The current moment F-012 matches an asset against (sourced upstream from F-006)."""

    time_of_day: str = ""
    activity: str = ""
    location: str = ""
    mood: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "PhotoContext":
        if isinstance(data, cls):
            return data
        data = data or {}
        return cls(
            time_of_day=str(data.get("time_of_day", "")),
            activity=str(data.get("activity", "")),
            location=str(data.get("location", "")),
            mood=str(data.get("mood", "")),
        )

    def as_dict(self) -> dict:
        return {
            "time_of_day": self.time_of_day,
            "activity": self.activity,
            "location": self.location,
            "mood": self.mood,
        }


# ── result ────────────────────────────────────────────────────────────────────────────────────────


class DeliveryOutcome(str, Enum):
    delivered = "delivered"              # a photo was selected, captioned, and recorded
    deflected = "deflected"              # nothing fits → in-voice deflection (caller sends text)
    paced = "paced"                      # relationship frequency cap reached → in-voice deflection
    routed_to_gate = "routed_to_gate"    # intimate/ambiguous → handed to F-014


# The slot fields of MEDIA_ASSET.meta_json that describe **what is visible** in a photo (F-008
# FR-008-08, authored by F-010's SlotMeta). Only these ever leave the delivery boundary: meta_json
# also carries generation provenance (`prompt`, `seed`) which must never reach the chat prompt
# (FR-012-14).
# FR-012-16 (ISS-008): `scene_description` first — it is the only field that says what is VISIBLE;
# the rest describe the generation request and remain as fallback for older assets.
SCENE_FIELDS = ("scene_description", "background", "location", "activity", "pose", "time_of_day")


def asset_scene(asset: MediaAsset) -> dict:
    """The delivered asset's scene descriptors — background/location/activity/pose/time_of_day.

    FR-012-14 (ISS-006): the Media Delivery contract of architecture.md §2/§3.6/§4.2 is "return the
    media **plus its metadata** so the Orchestrator/LLM knows what she sent". Provenance fields are
    stripped; empty/blank values are dropped so callers never render an empty descriptor."""
    meta = parse_meta(asset)
    scene = {}
    for key in SCENE_FIELDS:
        value = str(meta.get(key) or "").strip()
        if value:
            scene[key] = value
    return scene


@dataclass
class DeliveryResult:
    outcome: DeliveryOutcome
    asset: MediaAsset | None = None
    caption: str | None = None
    deflection: str | None = None        # in-voice line the caller sends when not delivering
    gate_result: Any = None              # F-014's own result when routed_to_gate
    # FR-012-14 (ISS-006): the delivered asset's scene descriptors, so the caller can feed **what she
    # just showed him** back into the conversation context (F-002 FR-002-25). Empty on every
    # non-delivered outcome — a photo that was never sent has no scene.
    meta: dict = field(default_factory=dict)

    @property
    def delivered(self) -> bool:
        return self.outcome is DeliveryOutcome.delivered


@dataclass(frozen=True)
class RecentSend:
    """One photo this user has already received, with what is visible in it (FR-012-15, ISS-006)."""

    asset_id: str
    sent_at: datetime
    scene: dict = field(default_factory=dict)


# ── context-fit scoring + selection (FR-012-01/03) ───────────────────────────────────────────────


def _slot_distance(a: str, b: str, slots: tuple[str, ...]) -> int | None:
    """Cyclic distance between two time-of-day slots on the ladder, or None if either is unknown."""
    a, b = a.lower().strip(), b.lower().strip()
    if a not in slots or b not in slots:
        return None
    i, j = slots.index(a), slots.index(b)
    d = abs(i - j)
    return min(d, len(slots) - d)


def _tag_score(asset_tag: Any, ctx_value: str, weight: float) -> float:
    """Full weight when the context value matches the asset tag (equal or substring either way)."""
    at = str(asset_tag or "").lower().strip()
    cv = (ctx_value or "").lower().strip()
    if not at or not cv:
        return 0.0
    if at == cv or cv in at or at in cv:
        return weight
    return 0.0


def score_asset(asset: MediaAsset, context: Any, cfg: MediaDeliveryConfig = DEFAULT_CONFIG) -> float:
    """Context-fit score for one asset against the current moment (higher = better slot match)."""
    ctx = PhotoContext.from_dict(context)
    meta = parse_meta(asset)
    score = 0.0

    a_tod = str(meta.get("time_of_day", "")).lower().strip()
    c_tod = ctx.time_of_day.lower().strip()
    if a_tod and c_tod:
        if a_tod == c_tod:
            score += cfg.weight_time_of_day
        else:
            dist = _slot_distance(a_tod, c_tod, cfg.time_slots)
            if dist is not None:
                score += max(0.0, cfg.weight_time_of_day - dist * cfg.slot_adjacency_penalty)

    score += _tag_score(meta.get("activity"), ctx.activity, cfg.weight_activity)
    score += _tag_score(meta.get("location"), ctx.location, cfg.weight_location)
    score += _tag_score(meta.get("mood"), ctx.mood, cfg.weight_mood)
    return score


def asset_age_days(asset: MediaAsset, now: datetime | None = None) -> float:
    """Whole days between the asset's creation and `now` (never negative)."""
    now = now or datetime.now(timezone.utc)
    created = asset.created_at
    if created is None:
        return 0.0
    if created.tzinfo is None:  # SQLite hands back naive datetimes
        created = created.replace(tzinfo=timezone.utc)
    return max(0.0, (now - created).total_seconds() / 86400.0)


def freshness_bonus(
    asset: MediaAsset, cfg: MediaDeliveryConfig = DEFAULT_CONFIG, now: datetime | None = None
) -> float:
    """Today's frames rank highest; the bonus decays proportionally with age (FR-021-02).

    `bonus / (1 + age_days * decay)` — strictly non-increasing in age and never negative, so it can
    reorder equals but never inverts them. Proportional decay is what makes the two documented
    regimes real: a large bonus keeps today ahead of *any* fit advantage ("today only in practice"),
    a near-zero one yields variety-first. `decay = 0` means age is ignored entirely.
    """
    age = int(asset_age_days(asset, now))
    bonus = max(0.0, cfg.freshness_bonus)
    decay = max(0.0, cfg.freshness_decay_per_day)
    return bonus / (1.0 + age * decay)


def rank_score(
    asset: MediaAsset, context: Any, cfg: MediaDeliveryConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> float:
    """Context fit + freshness — the value selection actually maximises (FR-021-02/03).

    Because both live on one scale, "materially better fit beats freshness" needs no second knob:
    an older frame wins exactly when its fit advantage exceeds the freshness bonus it gives up (D7).
    """
    return score_asset(asset, context, cfg) + freshness_bonus(asset, cfg, now)


async def sent_asset_ids(db: AsyncSession, user_id: int) -> set[str]:
    """The set of asset ids this user has already received (per-user isolation — NFR-012-06)."""
    rows = (
        await db.execute(select(MediaSend.asset_id).where(MediaSend.user_id == user_id))
    ).scalars().all()
    return set(rows)


async def select_asset(
    db: AsyncSession,
    *,
    persona_id: int,
    user_id: int,
    context: Any,
    cfg: MediaDeliveryConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
    exclude: set[str] | None = None,
) -> MediaAsset | None:
    """Pick the best-matching **SFW, unsent** asset from the whole retained library (FR-021-01).

    Pure lookup + rank — no generation (FR-012-04). The candidate set used to be *one day*
    (`latest_available_assets`): today's frames, or, if today was empty, the most recent prior day's.
    Measured live, that made 6 of Alina's 12 frames **permanently unreachable** the moment a newer
    day existed — paid-for GPU work sitting on disk while the user got a deflection. F-021 turns
    freshness into a ranking signal (`rank_score`) so every retained frame stays eligible and today's
    still wins all else equal. Returns None when nothing fits/unsent remains, so the caller can
    degrade in-voice (FR-012-08).
    """
    assets = await retained_assets(db, persona_id)
    seen = await sent_asset_ids(db, user_id)
    # SFW path NEVER serves an intimate asset (NFR-012-08); never a repeat (NFR-012-02). Widening
    # changes AGE eligibility only — it must not smuggle in anything otherwise ineligible.
    seen = seen | (exclude or set())
    candidates = [a for a in assets if not a.intimate and a.id not in seen]
    if not candidates:
        return None
    # Deterministic: highest fit+freshness, ties broken by id (NFR-005-13-style reproducibility).
    return max(candidates, key=lambda a: (rank_score(a, context, cfg, now), a.id))


# ── relationship pacing (FR-012-06 / NFR-012-04) ─────────────────────────────────────────────────


async def _stage_for(db: AsyncSession, user_id: int, persona_id: int) -> str:
    """Read the F-005 bond stage for (user, persona); a bond that doesn't exist yet is a Stranger."""
    rel = await db.scalar(
        select(Relationship).where(
            Relationship.user_id == user_id, Relationship.persona_id == persona_id
        )
    )
    return rel.stage if rel is not None else "Stranger"


def stage_cap(stage: str, cfg: MediaDeliveryConfig = DEFAULT_CONFIG) -> int:
    return cfg.stage_caps.get(stage, cfg.stage_caps.get("Stranger", 1))


async def sends_in_window(
    db: AsyncSession, user_id: int, cfg: MediaDeliveryConfig, now: datetime
) -> int:
    """How many photos this user has been sent within the pacing window (per-user — NFR-012-06)."""
    window_start = now - timedelta(hours=cfg.pacing_window_hours)
    count = await db.scalar(
        select(func.count())
        .select_from(MediaSend)
        .where(MediaSend.user_id == user_id, MediaSend.sent_at >= window_start)
    )
    return int(count or 0)


async def pacing_allows(
    db: AsyncSession,
    *,
    user_id: int,
    stage: str,
    cfg: MediaDeliveryConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> bool:
    """True while the user is under the per-stage cap for the current window (FR-012-06)."""
    now = now or _utcnow()
    used = await sends_in_window(db, user_id, cfg, now)
    return used < stage_cap(stage, cfg)


# ── send recording (FR-012-10, §3.6) ─────────────────────────────────────────────────────────────


async def recent_sends(
    db: AsyncSession,
    *,
    user_id: int,
    persona_id: int,
    cfg: MediaDeliveryConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> list[RecentSend]:
    """The photos this user has recently received from this persona, newest first (FR-012-15).

    One bounded `MediaSend ⋈ MediaAsset` query — no generation, no LLM call (FR-012-04) — capped at
    `cfg.context_recent_sends` rows inside `cfg.context_recency_hours` and strictly scoped to this
    (user, persona) pair (NFR-012-06). Feeds the F-002 context block that lets her talk about her own
    photos consistently instead of inventing a scene (ISS-006)."""
    limit = max(0, int(cfg.context_recent_sends))
    if limit == 0:
        return []
    now = now or _utcnow()
    window_start = now - timedelta(hours=cfg.context_recency_hours)
    rows = (
        await db.execute(
            select(MediaSend, MediaAsset)
            .join(MediaAsset, MediaAsset.id == MediaSend.asset_id)
            .where(
                MediaSend.user_id == user_id,
                MediaAsset.persona_id == persona_id,
                MediaSend.sent_at >= window_start,
            )
            .order_by(MediaSend.sent_at.desc(), MediaSend.id.desc())
            .limit(limit)
        )
    ).all()
    out: list[RecentSend] = []
    for send, asset in rows:
        sent_at = send.sent_at
        if sent_at is not None and sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes
        out.append(RecentSend(asset_id=asset.id, sent_at=sent_at or now, scene=asset_scene(asset)))
    return out


async def record_send(
    db: AsyncSession, *, user_id: int, asset: MediaAsset, now: datetime | None = None
) -> MediaSend:
    """Append the send to per-user history (which user, which asset, when) — FR-012-02/10."""
    send = MediaSend(user_id=user_id, asset_id=asset.id, sent_at=now or _utcnow())
    db.add(send)
    await db.flush()
    return send


# ── in-voice text via the chat client (FR-012-05, FR-012-08) ─────────────────────────────────────


# FR-012-12 (ISS-003): every user-visible line must be in the persona's own language — an English
# caption under a Russian-speaking persona breaks the single-voice illusion as hard as an
# out-of-character line. Keyed by `PERSONA.language`, falling back to "en".
_LANGUAGE_NAMES = {"ru": "Russian", "en": "English"}

_FALLBACK_CAPTION = {
    "ru": "подумала о тебе 💭",
    "en": "thought of you 💭",
}
_FALLBACK_DEFLECTION = {
    "ru": {
        "exhausted": "мм, сейчас нет ничего подходящего… позже? 😊",
        "paced": "какой нетерпеливый 😄 дай мне немного пожить, потом скину",
    },
    "en": {
        "exhausted": "mm, I don't have a good one to send right now — later? 😊",
        "paced": "you're eager 😄 let me actually go live a little first, then I'll send one",
    },
}


def _persona_language(persona: Persona) -> str:
    """Her language code, defaulting to English (FR-012-12)."""
    lang = (getattr(persona, "language", "") or "").strip().lower()
    return lang if lang in _LANGUAGE_NAMES else "en"


def fallback_caption(persona: Persona) -> str:
    return _FALLBACK_CAPTION[_persona_language(persona)]


def fallback_deflection(persona: Persona, reason: str) -> str:
    lines = _FALLBACK_DEFLECTION[_persona_language(persona)]
    return lines.get(reason, lines["exhausted"])


async def request_caption(
    caption_client: CaptionClient,
    *,
    persona: Persona,
    asset: MediaAsset,
    context: Any,
    stage: str,
) -> str:
    """Ask the chat LLM for ONE short caption in her voice (F-002/F-003) — never authored here."""
    ctx = PhotoContext.from_dict(context)
    meta = parse_meta(asset)
    scene = ", ".join(
        p for p in (
            meta.get("activity") or ctx.activity,
            meta.get("location") or ctx.location,
            meta.get("time_of_day") or ctx.time_of_day,
        ) if p
    )
    language = _LANGUAGE_NAMES[_persona_language(persona)]
    system = (
        f"You are {persona.name}. Write ONE short, natural first-person caption for a photo you're "
        f"sending him right now — at most ~12 words, in character, no quotes, no stage directions. "
        # FR-012-12 (ISS-003): she must caption in the language she actually speaks.
        f"Write it in {language} — this is the language you speak with him."
    )
    user = f"Photo of you: {scene or 'a candid moment'}. Mood: {ctx.mood or 'natural'}."
    try:
        text = await caption_client.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
    except Exception:  # noqa: BLE001 — chat client down must never crash the turn (degrade to a line)
        return fallback_caption(persona)
    return (text or "").strip() or fallback_caption(persona)


async def request_deflection(
    caption_client: CaptionClient, *, persona: Persona, reason: str, context: Any
) -> str:
    """Ask the chat LLM for ONE in-voice line declining a photo right now (FR-012-08). Falls back to
    a safe in-voice line if the client is unavailable — never an error/placeholder/repeat."""
    ctx = PhotoContext.from_dict(context)
    why = {
        "exhausted": "you don't have a good photo to send at this moment",
        "paced": "you just sent one and want to keep it feeling special, not spammy",
    }.get(reason, "you can't send a photo right now")
    language = _LANGUAGE_NAMES[_persona_language(persona)]
    system = (
        f"You are {persona.name}. In ONE short, warm first-person line, gently say {why}. Stay fully "
        f"in character — no apology-as-a-bot, no mention of systems, archives, or limits. "
        # FR-012-12 (ISS-003): the deflection is her voice too — same language rule as the caption.
        f"Write it in {language} — this is the language you speak with him."
    )
    user = f"Current moment: {ctx.activity or 'chatting'}."
    try:
        text = await caption_client.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
    except Exception:  # noqa: BLE001
        text = ""
    return (text or "").strip() or fallback_deflection(persona, reason)


# ── entrypoints ──────────────────────────────────────────────────────────────────────────────────


# §6.3: assets live at <media_root>/<slug>/photos/<MED-id>.png. Resolution lives HERE (domain)
# because delivery must verify the file before committing to a send; the handler re-exports it.
log = logging.getLogger(__name__)

DEFAULT_MEDIA_ROOT = Path(__file__).resolve().parents[3] / "media"


def asset_abspath(asset: MediaAsset, media_root: str | Path | None = None) -> Path:
    """Resolve a MEDIA_ASSET.storage_ref (media/<slug>/photos/<id>.png) to an on-disk path."""
    root = Path(media_root) if media_root is not None else DEFAULT_MEDIA_ROOT
    return root / asset.storage_ref.removeprefix("media/")


def asset_file_exists(asset: MediaAsset, media_root: str | Path | None = None) -> bool:
    return asset_abspath(asset, media_root).exists()


async def select_deliverable_asset(
    db: AsyncSession,
    *,
    persona_id: int,
    user_id: int,
    context: Any,
    cfg: MediaDeliveryConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
    media_root: str | Path | None = None,
    max_attempts: int = 3,
) -> MediaAsset | None:
    """`select_asset`, but the winner's **file must actually exist** (F-021 NFR-021-01).

    A row without its file is normally impossible (F-008 writes the file first), but it becomes
    reachable the moment retention deletes: a frame can be selected and evicted before the send
    completes. The send was recorded regardless, so the user "consumed" a photo he never saw and
    per-user no-repeat then excluded it **forever** — a paid-for frame destroyed by our own
    maintenance pass. Verifying before committing keeps that impossible: the missing frame is
    skipped, the next-best is served, and only a genuinely empty pool degrades in voice.
    """
    excluded: set[str] = set()
    for _ in range(max(1, max_attempts)):
        asset = await select_asset(
            db, persona_id=persona_id, user_id=user_id, context=context, cfg=cfg, now=now,
            exclude=excluded,
        )
        if asset is None:
            return None
        if asset_file_exists(asset, media_root):
            return asset
        log.warning("asset %s has no file — skipping it for this delivery", asset.id)
        excluded.add(asset.id)
    return None


async def deliver_photo(
    db: AsyncSession,
    *,
    user_id: int,
    persona: Persona,
    request_text: str,
    context: Any,
    caption_client: CaptionClient,
    gate: IntimacyGate,
    cfg: MediaDeliveryConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
    force_gate: bool = False,
    media_root: str | Path | None = None,
) -> DeliveryResult:
    """Serve an SFW photo on request (the on-request flow, feature §2).

    classify → (route intimate/ambiguous to the F-014 gate) → pace by relationship → select an
    unsent, context-matched SFW asset → caption in her voice → record the send. No hot-path
    generation (FR-012-04): only `store` lookups run here."""
    now = now or _utcnow()
    persona_id = persona.id

    # F-020: when the MODEL's signal judged the ask intimate, that verdict is authoritative — it
    # understands phrasing the keyword classifier cannot. The local classifier still runs as a
    # second opinion, and either saying "gate" sends it to the gate (never leak an intimate asset).
    kind = classify_photo_request(request_text)
    if force_gate or routes_to_gate(kind):
        stage = await _stage_for(db, user_id, persona_id)
        gate_result = await gate.handle_intimate_request(
            user_id=user_id,
            persona_id=persona_id,
            stage=stage,
            request_text=request_text,
            context=PhotoContext.from_dict(context).as_dict(),
        )
        return DeliveryResult(outcome=DeliveryOutcome.routed_to_gate, gate_result=gate_result)

    stage = await _stage_for(db, user_id, persona_id)
    if not await pacing_allows(db, user_id=user_id, stage=stage, cfg=cfg, now=now):
        line = await request_deflection(caption_client, persona=persona, reason="paced", context=context)
        return DeliveryResult(outcome=DeliveryOutcome.paced, deflection=line)

    asset = await select_deliverable_asset(
        db, persona_id=persona_id, user_id=user_id, context=context, cfg=cfg, now=now,
        media_root=media_root,
    )
    if asset is None:
        line = await request_deflection(
            caption_client, persona=persona, reason="exhausted", context=context
        )
        return DeliveryResult(outcome=DeliveryOutcome.deflected, deflection=line)

    caption = await request_caption(
        caption_client, persona=persona, asset=asset, context=context, stage=stage
    )
    await record_send(db, user_id=user_id, asset=asset, now=now)
    # FR-012-14 (ISS-006): hand the scene back so the turn pipeline can put it in her context.
    return DeliveryResult(
        outcome=DeliveryOutcome.delivered, asset=asset, caption=caption, meta=asset_scene(asset)
    )


async def maybe_proactive_share(
    db: AsyncSession,
    *,
    user_id: int,
    persona: Persona,
    context: Any,
    caption_client: CaptionClient,
    cfg: MediaDeliveryConfig = DEFAULT_CONFIG,
    now: datetime | None = None,
) -> DeliveryResult | None:
    """Maybe send a photo unprompted when the conversation matches her activity and pacing allows
    (FR-012-09). Returns a delivered result, or None when she shouldn't share right now."""
    now = now or _utcnow()
    persona_id = persona.id

    stage = await _stage_for(db, user_id, persona_id)
    if stage_index(stage) < stage_index(cfg.proactive_stage_floor):
        return None  # she only volunteers photos once at least this bonded
    if not await pacing_allows(db, user_id=user_id, stage=stage, cfg=cfg, now=now):
        return None

    asset = await select_asset(
        db, persona_id=persona_id, user_id=user_id, context=context, cfg=cfg, now=now
    )
    if asset is None:
        return None
    if score_asset(asset, context, cfg) < cfg.proactive_min_score:
        return None  # only share unprompted when the moment genuinely fits

    caption = await request_caption(
        caption_client, persona=persona, asset=asset, context=context, stage=stage
    )
    await record_send(db, user_id=user_id, asset=asset, now=now)
    return DeliveryResult(
        outcome=DeliveryOutcome.delivered, asset=asset, caption=caption, meta=asset_scene(asset)
    )
