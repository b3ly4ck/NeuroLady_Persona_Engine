"""F-012 ↔ F-014 wiring: the real intimacy gate behind media_delivery's `IntimacyGate` protocol.

F-012 routes any intimate/ambiguous photo request here (never serving it from the SFW archive);
this adapter loads the user/persona, reads the F-005 relationship stage, and runs F-014's
end-to-end `process_intimate_request` (hard safety gate → age/consent → stage unlock → ceiling →
deliver-or-enqueue). The result rides back on `DeliveryResult.gate_result` as
`(GateVerdict, FulfillResult)` for the handler to voice.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.domain import intimacy_gate
from services.bot.domain import relationship_store
from services.bot.models import Persona, User
from services.bot.personas_seed import persona_slug

# One process-wide pacer: intimate delivery pace survives across turns within a bot run
# (F-014 FR-014-07; a DB-backed pacer can replace it without changing this surface).
_PACER = intimacy_gate.InMemoryPacer(per_user_cap=3)


class F014GateAdapter:
    """Satisfies `media_delivery.IntimacyGate` with the real F-014 gate."""

    def __init__(self, db: AsyncSession, requested_level: int = 1) -> None:
        self._db = db
        self._requested_level = requested_level

    async def handle_intimate_request(
        self, *, user_id: int, persona_id: int, stage: str, request_text: str, context: Any,
    ) -> tuple[intimacy_gate.GateVerdict, intimacy_gate.FulfillResult] | None:
        db = self._db
        user = await db.scalar(select(User).where(User.id == user_id))
        persona = await db.scalar(select(Persona).where(Persona.id == persona_id))
        if user is None or persona is None:
            return None
        if not stage:
            rel = await relationship_store.get_or_create(db, user.id, persona.id)
            stage = rel.stage
        refs = [r for r in (persona.face_ref, persona.fullbody_ref) if r]
        return await intimacy_gate.process_intimate_request(
            db,
            user=user,
            persona=persona,
            persona_slug=persona_slug(persona.name),
            stage=stage,
            requested_level=self._requested_level,
            request_text=request_text,
            pacer=_PACER,
            references=refs,
        )
