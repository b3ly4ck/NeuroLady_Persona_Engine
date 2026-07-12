"""SQLAlchemy models — a faithful subset of the ERD in architecture.md §5.1.

F-001 needs USER, PERSONA, and SESSION. Fields beyond F-001's immediate use (e.g. big_five,
comm_settings_json, the various media `*_ref` paths) are modelled now so later features
(F-002/F-003/F-004) don't require a migration to add them.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    locale: Mapped[str] = mapped_column(String(8), default="en")
    adult_verified: Mapped[bool] = mapped_column(default=False)
    # F-003 per-user comm overlay (nullable); unused by F-001.
    interaction_style_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    profession: Mapped[str] = mapped_column(String(128), default="")
    age: Mapped[int] = mapped_column(Integer, default=0)
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
