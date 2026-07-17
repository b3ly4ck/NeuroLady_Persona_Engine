"""SQLAlchemy models — a faithful subset of the ERD in architecture.md §5.1.

F-001 needs USER, PERSONA, and SESSION. Fields beyond F-001's immediate use (e.g. big_five,
comm_settings_json, the various media `*_ref` paths) are modelled now so later features
(F-002/F-003/F-004) don't require a migration to add them.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PersonaStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"


class SessionState(str, enum.Enum):
    active = "active"
    ended = "ended"


class MessageSender(str, enum.Enum):
    user = "user"
    persona = "persona"


class FactStatus(str, enum.Enum):
    active = "active"
    superseded = "superseded"


class GoalStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    dropped = "dropped"


class Horizon(str, enum.Enum):
    """Future-self projection horizons (F-006 FR-006-26, architecture.md §5.1 FUTURE_PROJECTION)."""
    week = "week"
    month = "month"
    year = "year"
    epoch = "epoch"
    lifetime = "lifetime"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    locale: Mapped[str] = mapped_column(String(8), default="en")
    adult_verified: Mapped[bool] = mapped_column(default=False)
    # F-014 intimacy gate: age/consent flags. `adult_verified` (above) + this opt-in are BOTH
    # required before any intimate content is served (FR-014-02). Append-only, default off.
    intimate_opt_in: Mapped[bool] = mapped_column(default=False)
    # F-003 per-user comm overlay (nullable); unused by F-001.
    interaction_style_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")
    facts: Mapped[list["UserFact"]] = relationship(back_populates="user")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    profession: Mapped[str] = mapped_column(String(128), default="")
    # `age` is a display fallback; her real age is DERIVED from `birthdate` (F-006 persona-time,
    # FR-006-24). Kept for personas without an authored birthdate / for the gallery card.
    age: Mapped[int] = mapped_column(Integer, default=0)
    # F-006 biography extension — FIXED identity anchors (immutable; FR-006-23). `birthdate` drives
    # the daily-versioned age; `core_values`/`motivation` are used verbatim and never contradicted.
    birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)
    core_values: Mapped[str] = mapped_column(Text, default="")
    motivation: Mapped[str] = mapped_column(Text, default="")
    # EVOLVING persona-time field (FR-006-25) — fed into the identity prompt, may change over time.
    interests: Mapped[str] = mapped_column(Text, default="")
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    # First-person gallery teaser (architecture.md §5.1 PERSONA.card_description).
    card_description: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="en")  # "ru" | "en"
    status: Mapped[PersonaStatus] = mapped_column(
        Enum(PersonaStatus), default=PersonaStatus.active, index=True
    )
    big_five: Mapped[str] = mapped_column(Text, default="")
    comm_settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Media paths into the external media/ library (architecture.md §5.1 / §6.3); nullable.
    face_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    fullbody_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    avatar_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    gallery_photo_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    intro_videonote_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    voice_profile_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("user_id", "persona_id", name="uq_user_persona"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    state: Mapped[SessionState] = mapped_column(
        Enum(SessionState), default=SessionState.active, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")
    persona: Mapped["Persona"] = relationship()
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", order_by="Message.id"
    )


class Message(Base):
    """One turn's message in a session (ERD §5.1 SESSION ||--o{ MESSAGE).

    F-002 persists both the inbound user message and the persona reply, with the correct `sender`
    and a monotonic order (FR-002-09). `media_asset_id` is modelled now (nullable) so the later
    media feature needs no migration; the MEDIA_ASSET table / FK arrives with that feature.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    sender: Mapped[MessageSender] = mapped_column(Enum(MessageSender), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    media_asset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session: Mapped["Session"] = relationship(back_populates="messages")


class UserFact(Base):
    """A categorized fact the user revealed about himself (ERD §5.1 USER ||--o{ USER_FACT, F-004).

    Structured (relational) half of the memory system. A fact carries a `category`, its `content`,
    a `status` (active|superseded) with `superseded_by` so a contradicted fact is soft-superseded
    and kept for history (FR-004-11/12), and a `confidence` so hedged remarks aren't recalled as
    certain (FR-004-14). `embedding_ref` is modelled now (nullable) for the future Qdrant/semantic
    half (FR-004-08) — unused in the Postgres-only slice.
    """

    __tablename__ = "user_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)  # family|work|preferences|...
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[FactStatus] = mapped_column(
        Enum(FactStatus), default=FactStatus.active, index=True
    )
    superseded_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_facts.id"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(default=1.0)  # 0..1, how firmly asserted (FR-004-14)
    embedding_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)  # future Qdrant
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    user: Mapped["User"] = relationship(back_populates="facts")


class Relationship(Base):
    """Per (user, persona) bond that evolves over time (ERD §5.1 RELATIONSHIP, F-005).

    Three integer dimensions (0–100) + a **derived** stage (never set directly — F-005 FR-005-03),
    a first-person `summary`, `last_interaction_at`, and a `pending_milestone` the persona may
    acknowledge in-character after crossing a stage boundary (FR-005-22). Authored by F-005, stored
    here in the Memory subsystem (FR-005-24). Strictly per-user isolated (FR-005-25).
    """

    __tablename__ = "relationships"
    __table_args__ = (UniqueConstraint("user_id", "persona_id", name="uq_rel_user_persona"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    closeness: Mapped[int] = mapped_column(Integer, default=5)
    trust: Mapped[int] = mapped_column(Integer, default=5)
    attraction: Mapped[int] = mapped_column(Integer, default=5)
    stage: Mapped[str] = mapped_column(String(16), default="Stranger")
    summary: Mapped[str] = mapped_column(Text, default="")
    pending_milestone: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    reflections: Mapped[list["RelationshipReflection"]] = relationship(
        back_populates="relationship", order_by="RelationshipReflection.id"
    )


class RelationshipReflection(Base):
    """Audit log of one applied relationship reflection (ERD §5.1, F-005 FR-005-10).

    Records the per-dimension deltas + reasons, the resulting stage, and the time — so every
    relationship change is traceable and explainable (NFR-005-07).
    """

    __tablename__ = "relationship_reflections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    relationship_id: Mapped[int] = mapped_column(ForeignKey("relationships.id"), index=True)
    delta_closeness: Mapped[int] = mapped_column(Integer, default=0)
    delta_trust: Mapped[int] = mapped_column(Integer, default=0)
    delta_attraction: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[str] = mapped_column(Text, default="")  # one line per dimension
    resulting_stage: Mapped[str] = mapped_column(String(16), default="Stranger")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    relationship: Mapped["Relationship"] = relationship(back_populates="reflections")


class DailyPlan(Base):
    """The persona's morning-authored schedule for one local day (ERD §5.1, F-006 FR-006-01/04).

    No structured slot table — the schedule is **free text** (`plan_text`); current activity is
    derived from it + the current time (architecture.md §3.5). One row per (persona, date).
    """

    __tablename__ = "daily_plans"
    __table_args__ = (UniqueConstraint("persona_id", "date", name="uq_plan_persona_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD" in her local timezone
    plan_text: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")  # audit (FR-006-19/21)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Reflection(Base):
    """A persona's own first-person daily reflection (ERD §5.1 REFLECTION, F-006 FR-006-05/06).

    Shared persona config — about her own life, never a specific user's private facts
    (FR-006-06). `source_period` records provenance (what it was derived from) for auditability
    (FR-006-21).
    """

    __tablename__ = "reflections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16), default="day", index=True)  # daily reflections
    period_key: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD"
    content: Mapped[str] = mapped_column(Text, default="")
    source_period: Mapped[str] = mapped_column(Text, default="")  # provenance (FR-006-21)
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class BiographyLayer(Base):
    """A compressed biography layer at week/month/year/epoch scope (ERD §5.1 BIOGRAPHY_LAYER,
    F-006 FR-006-07/08/09). Authored by the Life Engine, handed to Memory (F-004) for storage +
    embedding; `embedding_ref` links to the vector point once indexed. `source_period` records what
    was compressed (provenance — FR-006-21), e.g. the date range or source ids.
    """

    __tablename__ = "biography_layers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)  # epoch|year|month|week
    period_key: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    source_period: Mapped[str] = mapped_column(Text, default="")
    embedding_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Goal(Base):
    """A persona's own goal, giving her direction beyond reactivity (ERD §5.1 GOAL, F-006
    FR-006-11/12/13). Shared persona config, not per-user.
    """

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[GoalStatus] = mapped_column(Enum(GoalStatus), default=GoalStatus.active, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 (low) .. 5 (high)
    horizon: Mapped[str] = mapped_column(String(16), default="medium")  # short|medium|long
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class FutureProjection(Base):
    """A persona's first-person "future me" at one horizon (ERD §5.1 FUTURE_PROJECTION, F-006
    FR-006-26). Forward-facing counterpart of BIOGRAPHY_LAYER; seeded and thereafter authorable,
    kept consistent with goals + biography. One row per (persona, horizon) — upserted.
    """

    __tablename__ = "future_projections"
    __table_args__ = (UniqueConstraint("persona_id", "horizon", name="uq_future_persona_horizon"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    horizon: Mapped[Horizon] = mapped_column(Enum(Horizon), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")  # audit (FR-006-21)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class MediaKind(str, enum.Enum):
    """MEDIA_ASSET.kind (ERD §5.1; F-008 kind=photo, F-015 adds video_keyframe)."""
    photo = "photo"
    video_keyframe = "video_keyframe"


class MediaJobStatus(str, enum.Enum):
    """F-008 job lifecycle: pending → running → done | failed (given up) | skipped."""
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class MediaAsset(Base):
    """A generated media file in the external media/ library (ERD §5.1 MEDIA_ASSET; F-008
    FR-008-07/08). `id` is the MED-<persona_slug>-<nnnnn> scheme and equals the file stem, so the
    DB row and the archive file map 1:1 (NFR-008-05). The row is inserted only after the file is
    durably written (FR-008-09).
    """

    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)  # MED-<slug>-<nnnnn>
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    kind: Mapped[MediaKind] = mapped_column(Enum(MediaKind), default=MediaKind.photo, index=True)
    intimate: Mapped[bool] = mapped_column(default=False, index=True)
    intimacy_level: Mapped[int] = mapped_column(Integer, default=0)
    # Relative path inside the media library, e.g. media/<slug>/photos/<MED-id>.png (§6.3).
    storage_ref: Mapped[str] = mapped_column(String(256))
    # pose / background / location / activity / time_of_day + prompt provenance (F-010 FR-010-08).
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MediaJob(Base):
    """One queued generation request for the F-008 runner (fixed job API, FR-008-01).

    `job_key` is the idempotency key (FR-008-12): enqueueing or re-processing the same key never
    yields a second asset. `attempts`/`next_attempt_at` drive retry-with-backoff (FR-008-13);
    `running` rows older than a staleness cutoff are requeued on the next batch (FR-008-14 resume).
    The payload is the full job contract JSON (services/imagegen/contract.py).
    """

    __tablename__ = "media_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[MediaJobStatus] = mapped_column(
        Enum(MediaJobStatus), default=MediaJobStatus.pending, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class MediaSend(Base):
    """Append-only log of one photo delivered to one user (F-012 FR-012-02/10, §3.6).

    The per-user sent-history that guarantees **no asset is ever resent** to the same user
    (NFR-012-02) and the audit trail for a media send (which user, which asset, when). Rows are
    only ever inserted, never updated — the history is the source of truth for the no-repeat filter
    and for relationship-paced frequency counting (FR-012-06). Strictly per-user (NFR-012-06): a
    selection for one user reads only that user's rows.
    """

    __tablename__ = "media_sends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class GateDecision(Base):
    """Append-only audit log of one F-014 intimacy-gate decision (FR-014-12 / NFR-014-08).

    Every gate evaluation — allow / withhold / block — is recorded here for safety review. The row
    stores the outcome only: `action`, `reason`, the prohibited `category` (block only), the
    requested level, the effective ceiling, and the stage. The **prohibited request text is never
    persisted** — only the category/reason — so the audit trail carries no prohibited content.
    """

    __tablename__ = "gate_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id"), index=True)
    action: Mapped[str] = mapped_column(String(16), index=True)   # allow | withhold | block
    reason: Mapped[str] = mapped_column(String(24), index=True)   # ok | hard_safety | not_adult | ...
    category: Mapped[str | None] = mapped_column(String(32), nullable=True)  # prohibited category (block)
    requested_level: Mapped[int] = mapped_column(Integer, default=0)
    effective_ceiling: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str] = mapped_column(String(16), default="Stranger")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
