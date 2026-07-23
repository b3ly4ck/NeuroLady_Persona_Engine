"""Conversation Orchestrator — one user turn end-to-end (architecture.md §3.2, DFD-1, F-002).

Message intake → load session → assemble context (persona system prompt + recalled user facts +
**relationship stage/behaviour** + **her current activity** + **the photos she recently sent him** +
recent raw history) → call the Chat-LLM runner → post-process → in-character reply → persist both
MESSAGE rows; then, off the hot path, extract + store the user's facts (F-004) and run the
relationship reflection (F-005). Memory (F-004, structured + semantic), the relationship model
(F-005), her Life Engine activity (F-006), and the F-012 media she has already sent are wired in
here.

Requirements realized here: FR-002-03/04 (assemble context incl. recent raw history verbatim),
FR-002-05 (call the LLM), FR-002-06 (post-process), FR-002-07 (in-character reply), FR-002-09
(persist the exchange), FR-002-17 (empty-history first turn), FR-002-19 (timeout/fail → graceful
in-character fallback, logged, user message still persisted, never silent), FR-002-25/26 (bounded
recently-sent-media descriptors in context — ISS-006).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.chat_client import ChatClient, ChatRunnerUnavailable
from services.bot.domain import biography as bio_domain
from services.bot.domain import life_engine_store as life_store
from services.bot.domain import media_delivery
from services.bot.domain import media_intent as intent_domain
from services.bot.domain import memory as memory_domain
from services.bot.domain import messages as msg_domain
from services.bot.domain import relationship_store as rel_store
from services.bot.domain.fact_extraction import extract_memory_ops
from services.bot.domain.media_delivery import DEFAULT_CONFIG as MEDIA_DEFAULT_CONFIG
from services.bot.domain.media_delivery import MediaDeliveryConfig
from services.bot.domain import prompt_log
from services.bot.domain.persona_prompt import build_system_prompt
from services.bot.domain.persona_time import today_in_tz
from services.bot.domain.relationship import (
    DEFAULT_CONFIG,
    RelationshipConfig,
    stage_behavior_directive,
)
from services.bot.domain.relationship_reflection import HardSignals, compute_warmth, run_reflection
from services.bot.domain.vector_store import MemoryIndex
from services.bot.models import MessageSender, Persona, Relationship, Session, UserFact

log = logging.getLogger(__name__)

# In-character fallback when the runner can't answer (FR-002-19 / NFR-002-10) — never system voice.
_FALLBACK = {
    "ru": "ой, я на секунду отвлеклась… напиши ещё разок?",
    "en": "ugh sorry, my head's all over the place rn — say that again?",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fallback_text(persona: Persona) -> str:
    return _FALLBACK.get(persona.language, _FALLBACK["en"])


def _postprocess(text: str) -> str:
    """Minimal post-processing (FR-002-06, F-003 FR-003-41). Reasoning mode is ON at the runner:
    strip the private <think>…</think> block before delivery. A think block that never closes
    (token-truncated reasoning) must NEVER leak to the user — return empty so the caller degrades
    to the in-character fallback."""
    if "</think>" in text:
        text = text.split("</think>")[-1]
    elif "<think>" in text:
        return ""  # truncated reasoning — never deliver raw thought text (FR-003-41)
    elif text.lstrip().lower().startswith("thinking process"):
        # The chat template opens <think> inside the *prompt*, so a token-truncated CoT arrives
        # tagless as plain "Thinking Process: …" text (observed live). Never deliver it.
        return ""
    return text.strip()


def _memory_block(facts: list[UserFact], language: str) -> str | None:
    """Render recalled user facts as a system-context block (F-004 fused into the prompt, §4.2)."""
    if not facts:
        return None
    lines = "\n".join(f"- {f.content}" for f in facts)
    if language == "ru":
        return (
            "Что ты помнишь о нём (упоминай естественно и только когда уместно, "
            "не вываливай списком):\n" + lines
        )
    return (
        "What you remember about him (bring up naturally and only when relevant, "
        "don't dump it as a list):\n" + lines
    )


def _relationship_block(rel: Relationship, language: str) -> str:
    """Render the relationship state as a stage-gated behavior directive (F-005 FR-005-19/20).

    Feeds the current stage's behaviour + her private summary into the prompt so her openness/
    flirtiness/intimacy match where they stand — never leaking numbers or stage names (NFR-005-10).
    A pending milestone lets her acknowledge growing closer, in-character (FR-005-22/23).
    """
    parts = [stage_behavior_directive(rel.stage)]
    if rel.summary:
        parts.append(("Как ты сейчас чувствуешь ваши отношения: " if language == "ru"
                      else "How you privately feel about him right now: ") + rel.summary)
    if rel.pending_milestone:
        parts.append(
            "Ты чувствуешь, что вы стали ближе — можешь мимоходом это признать, по-человечески, "
            "без цифр и формальностей." if language == "ru" else
            "You feel you've grown closer — you may acknowledge that in passing, naturally, "
            "with no numbers or mechanics."
        )
    return "\n".join(parts)


_WEEKDAYS_RU = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def _local_time_block(persona: Persona, now_utc: datetime | None = None) -> str:
    """Ground her in her own local clock (F-006 FR-006-29) — any 'now' statement (what time it is,
    morning vs evening) must come from her real local time, never guessed from plan-text flavor
    (live-caught: she said "around noon" at 19:00 Moscow because the prompt carried no clock)."""
    from services.bot.domain.life_engine import local_now

    now = local_now(persona.timezone, now_utc or _now())
    if persona.language == "ru":
        return (f"Сейчас у тебя {_WEEKDAYS_RU[now.weekday()]}, местное время ≈ {now:%H:%M} "
                f"({now:%d.%m}). Ощущение времени суток бери отсюда.")
    return (f"Right now it is {now:%A}, about {now:%H:%M} your local time ({now:%b %d}). "
            f"Take your sense of the time of day from this.")


def _when_phrase(sent_at: datetime, now: datetime, language: str) -> str:
    """Roughly when a photo was sent, the way a person would say it (FR-002-25)."""
    minutes = max(0, int((now - sent_at).total_seconds() // 60))
    if language == "ru":
        if minutes < 5:
            return "только что"
        if minutes < 60:
            return f"{minutes} мин назад"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} ч назад"
        return "вчера" if hours < 48 else f"{hours // 24} дн назад"
    if minutes < 5:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    return "yesterday" if hours < 48 else f"{hours // 24} days ago"


# Order the scene descriptors are rendered in, with their user-facing labels (RU/EN). Only these
# five fields exist in the block — generation provenance (prompt/seed) never enters the prompt
# (FR-002-25, F-012 FR-012-14).
_SCENE_LABELS = {
    "ru": (("location", "место"), ("background", "на фоне"), ("activity", "что делаешь"),
           ("pose", "поза"), ("time_of_day", "время суток")),
    "en": (("location", "place"), ("background", "background"), ("activity", "doing"),
           ("pose", "pose"), ("time_of_day", "time of day")),
}


def _recent_media_block(sends: list, language: str, now: datetime | None = None) -> str | None:
    """Render the photos she recently sent him as a context block (F-002 FR-002-25/26, ISS-006).

    Without this she has **no evidence a photo ever existed**, so a question about it ("what's in
    the background?") gets answered from her biography — live-caught: she invented bookshelves, a
    saxophone and watercolours for a photo of her dim bedroom. The block states plainly that this is
    what he is looking at, and is bounded upstream by `recent_sends()` (FR-002-26)."""
    if not sends:
        return None  # nothing sent (or nothing recent) → no block at all, not an empty heading
    now = now or _now()
    labels = _SCENE_LABELS.get(language, _SCENE_LABELS["en"])
    lines = []
    for send in sends:
        parts = [f"{label}: {send.scene[key]}" for key, label in labels if send.scene.get(key)]
        if not parts:
            continue
        lines.append(f"- {_when_phrase(send.sent_at, now, language)} — " + "; ".join(parts))
    if not lines:
        return None
    if language == "ru":
        return (
            "Фото, которые ты ему недавно отправила — это ровно то, что он видит у себя в чате. "
            "Если он спрашивает про фото (что на фоне, где ты, что делаешь), отвечай именно по "
            "этому описанию и не придумывай другую обстановку:\n" + "\n".join(lines)
        )
    return (
        "Photos you recently sent him — this is exactly what he is looking at. If he asks about a "
        "photo (what's in the background, where you are, what you're doing), answer from this and "
        "never invent a different scene:\n" + "\n".join(lines)
    )


def _life_engine_block(activity: str | None, language: str) -> str | None:
    """Render her current activity (F-006 FR-006-03) as a system-context block so she can mention
    her day naturally — never a mechanical status line."""
    if not activity:
        return None
    if language == "ru":
        return f"Что ты сейчас делаешь по своим делам (можешь упомянуть, если уместно): {activity}"
    return f"What you're currently up to in your own life (mention it naturally if relevant): {activity}"


# F-020: `handle_turn` must keep returning a plain string (24 call sites depend on it), so the
# turn's media-intent verdict is handed over out-of-band, keyed by session. Read it immediately
# after the call with `take_media_intent(session.id)`; it is consumed (pop) so a later turn can
# never act on a stale verdict.
_LAST_INTENT: dict[int, "intent_domain.MediaIntent"] = {}


def take_media_intent(session_id: int) -> "intent_domain.MediaIntent":
    """Pop the media-intent verdict produced by the most recent `handle_turn` for this session."""
    return _LAST_INTENT.pop(session_id, intent_domain.NO_INTENT)


async def handle_turn(
    db: AsyncSession,
    session: Session,
    persona: Persona,
    user_text: str,
    chat_client: ChatClient,
    memory_index: MemoryIndex | None = None,
    media_cfg: MediaDeliveryConfig = MEDIA_DEFAULT_CONFIG,
) -> str:
    """Process one turn and return the reply text to send. Persists the user message and the reply.

    The user message is persisted *before* the LLM call so no input is lost if generation fails
    (FR-002-19).
    """
    # 1. Persist the inbound user message first (FR-002-09; input-preserved on failure FR-002-19).
    await msg_domain.append_message(db, session.id, MessageSender.user, user_text)

    # 2. Assemble the context: ONE system message (persona prompt + recalled memory) + recent raw
    #    history + this message. The Qwen chat template allows only a single leading system message,
    #    so memory/relationship context is concatenated into it, not added as extra system turns.
    #    (The recent window already includes the just-persisted user message.)  FR-002-03/04.
    history = await msg_domain.load_recent(db, session.id)
    # Persona-time identity: age derived from birthdate at her local date + her current top goal
    # (F-006 FR-006-24/25). Falls back cleanly for personas without a birthdate/goals.
    goals = await life_store.active_goals(db, persona.id)
    goal_text = goals[0].description if goals else None
    system_content = build_system_prompt(persona, today_in_tz(persona.timezone), goal_text)
    # F-004: fuse the user's relevant stored facts into the context so she "remembers" (FR-002-13/14,
    # FR-004-24/28). Semantic search when a vector index is available, else keyword recall.
    recalled = await memory_domain.recall_relevant(db, session.user_id, user_text, memory_index)
    mem_block = _memory_block(recalled, persona.language)
    if mem_block:
        system_content += "\n\n" + mem_block
    # F-005: gate her behaviour by the current relationship stage + feed her private summary
    # (FR-005-19/20). Read the last persisted state — never wait on a reflection (NFR-005-03).
    rel = await rel_store.get_or_create(db, session.user_id, session.persona_id)
    system_content += "\n\n" + _relationship_block(rel, persona.language)
    if rel.pending_milestone:
        await rel_store.clear_milestone(db, rel)  # offered once; don't repeat every turn
    # F-006: her real local clock first (FR-006-29), then her current activity (from the daily
    # plan + now) so she can bring up her own day naturally (FR-006-03). Activity degrades to
    # nothing if she's never been planned yet.
    system_content += "\n\n" + _local_time_block(persona)
    activity = await life_store.get_current_activity(db, persona.id, persona.timezone)
    life_block = _life_engine_block(activity, persona.language)
    if life_block:
        system_content += "\n\n" + life_block
    # F-006 biography: fuse her own life story into context — graded recency + semantically-relevant
    # deep layers (so a childhood question pulls her childhood) + future-self (FR-006-27/28). Uses the
    # persona-scoped biography_layers vector collection; degrades to "" if she isn't seeded yet.
    bio_index = memory_index.for_collection(life_store.BIOGRAPHY_COLLECTION) if memory_index else None
    bio_ctx = await bio_domain.assemble_biography_context(db, persona, user_text, bio_index)
    if bio_ctx:
        system_content += "\n\n" + bio_ctx
    # F-012 → F-002 (FR-002-25/26, ISS-006): what she recently SENT him. The photo metadata is
    # stored anyway (MEDIA_ASSET.meta_json); until it re-enters the prompt she has no idea what she
    # showed him and confabulates a scene out of her biography. Bounded lookup (count + window),
    # no LLM call, nothing generated — one cheap MediaSend ⋈ MediaAsset query.
    sends = await media_delivery.recent_sends(
        db, user_id=session.user_id, persona_id=persona.id, cfg=media_cfg
    )
    media_block = _recent_media_block(sends, persona.language)
    if media_block:
        system_content += "\n\n" + media_block
    # F-020 (FR-020-01): the turn instructs the model to emit a media-intent signal alongside its
    # reply, so intent is judged by the model that understands the conversation — not by a keyword
    # list that missed natural phrasing (ISS-005). No extra round-trip: it rides this same call.
    system_content += "\n\n" + intent_domain.intent_instruction()
    llm_messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    llm_messages += msg_domain.to_openai_messages(history)
    prompt_log.maybe_dump(persona.name, user_text, llm_messages)  # dev observability (opt-in via env)

    # 3. Call the Chat-LLM; on any failure fall back in-character (FR-002-05/19).
    # Commit the writes made so far (inbound message, relationship get_or_create/milestone) BEFORE
    # the long reasoning-inclusive generation: holding a SQLite write transaction open for 30-60s
    # locked out concurrent writers live ("database is locked" on the user's next message).
    await db.commit()
    raw = ""
    try:
        raw = _postprocess(await chat_client.complete(llm_messages))
        if not raw:  # empty or truncated-reasoning output — degrade, never a blank/leaked reply
            log.warning("post-processed reply empty (truncated reasoning?), using fallback")
            raw = _fallback_text(persona)
    except ChatRunnerUnavailable as exc:
        log.warning("chat runner unavailable, using in-character fallback: %s", exc)
        raw = _fallback_text(persona)
    except Exception:  # noqa: BLE001 — FR-002-28: ANY model failure degrades in character.
        # Previously only ChatRunnerUnavailable was caught, so e.g. a client bug propagated out of
        # the turn and (before the dispatcher safety net) left the user with silence.
        log.exception("chat generation failed, using in-character fallback")
        raw = _fallback_text(persona)

    # F-020: pull the media-intent verdict out of the reply and STRIP the signal before anything
    # user-visible or persisted (FR-020-04) — the token must never reach the chat or the history.
    # The keyword matcher is now only a fallback for a missing signal (FR-020-08 / D2).
    reply, media_intent = intent_domain.resolve(
        raw, user_text, keyword_fallback=media_delivery.looks_like_photo_request
    )
    if not reply:  # a signal-only reply still has to say something (FR-020-04, silence invariant)
        reply = _fallback_text(persona)

    # 4. Persist the persona reply so the thread stays coherent (FR-002-09).
    await msg_domain.append_message(db, session.id, MessageSender.persona, reply)
    # (F-005 relationship update + F-003 styling/pacing run in the handler after the reply is sent.)
    _LAST_INTENT[session.id] = media_intent
    return reply


async def update_user_memory(
    db: AsyncSession,
    user_id: int,
    user_text: str,
    chat_client: ChatClient,
    memory_index: MemoryIndex | None = None,
) -> list[UserFact]:
    """Extract salient facts from the user's message and store them (F-004 FR-004-06/07/11/15).

    Called by the handler **after the reply is delivered**, so this LLM extraction never delays the
    user-visible reply (FR-002-23 / FR-004-42/43). When a vector `index` is given, new facts are
    also embedded and superseded ones removed (FR-004-08/33). Returns the newly-stored facts. Never
    raises — a memory failure must not affect the already-sent reply.
    """
    try:
        existing = [(f.id, f.category, f.content) for f in await memory_domain.active_facts(db, user_id)]
        # FR-002-27 (ISS-007): release the write lock BEFORE the ~20-30 s extraction call. Holding a
        # SQLite write transaction across it starved the user's next message into
        # `database is locked` — and, with no safety net, into total silence.
        await db.commit()
        ops = await extract_memory_ops(chat_client, user_text, existing)
        if not ops.add and not ops.supersede:
            return []
        return await memory_domain.apply_memory_ops(db, user_id, ops, memory_index)
    except Exception:  # pragma: no cover - defensive: memory must never break the turn
        log.warning("user-memory update failed", exc_info=True)
        return []


async def update_relationship(
    db: AsyncSession,
    session: Session,
    persona: Persona,
    chat_client: ChatClient,
    cfg: RelationshipConfig = DEFAULT_CONFIG,
) -> Relationship | None:
    """Run a relationship reflection and apply it (F-005 FR-005-06/08/09/10).

    Called by the handler **after the reply is delivered** — off the hot path (NFR-005-03). Builds
    the reflection inputs from **this user's own** recent conversation only (FR-005-28), runs the
    LLM judgment, and applies bounded/clamped deltas + summary + audit log. On any failure (LLM
    down or unparseable) the last good state is preserved (FR-005-27 / NFR-005-04) — never raises.
    """
    try:
        rel = await rel_store.get_or_create(db, session.user_id, session.persona_id, cfg)
        history = await msg_domain.load_recent(db, session.id)
        # FR-002-27 (ISS-007): same rule — no open write transaction across the reflection call.
        await db.commit()
        conversation = "\n".join(
            f"{'he' if m.sender == MessageSender.user else 'you'}: {m.text}" for m in history)
        now = _now()
        last = rel.last_interaction_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)  # SQLite returns naive datetimes
        days_since = ((now - last).total_seconds() / 86400.0) if last else 0.0
        signals = HardSignals(days_since=days_since, msg_count=len(history),
                              warmth=compute_warmth(conversation))
        result = await run_reflection(
            chat_client, persona.name, persona.big_five,
            rel_store.to_state(rel), rel.summary, conversation, signals)
        if result is None:
            return rel  # LLM failure → last good state preserved (FR-005-27)
        await rel_store.apply_reflection(db, rel, result, cfg)
        return rel
    except Exception:  # pragma: no cover - defensive: a reflection must never break the turn
        log.warning("relationship update failed", exc_info=True)
        return None
