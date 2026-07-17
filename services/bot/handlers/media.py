"""F-012 media-delivery hook — the ONE small wiring block between chat and photo delivery.

Kept as a **standalone helper** (not a competing `F.text` router) so it never collides with the
conversation/persona-selection handlers edited in parallel (F-003/F-013). An orchestrator step can
call `serve_photo_request` when it detects a photo intent; everything below is a thin adapter over
`services.bot.domain.media_delivery` — the domain module owns all logic, this file only turns a
`DeliveryResult` into Telegram sends via the §3.6 Media path.
"""
from __future__ import annotations

import os
from pathlib import Path

from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from services.bot.chat_client import ChatClient
from services.bot.domain.media_delivery import (
    DeliveryResult,
    IntimacyGate,
    MediaDeliveryConfig,
    DEFAULT_CONFIG,
    deliver_photo,
)
from services.bot.models import MediaAsset, Persona

# The media library root (§6.3): <repo>/media by default. Resolved here from the repo layout so the
# reply/bot path never imports the night-batch generation package (F-008 NFR-008-04 keeps them
# apart); override per call via `media_root`.
_DEFAULT_MEDIA_ROOT = Path(__file__).resolve().parents[3] / "media"


def asset_abspath(asset: MediaAsset, media_root: str | Path | None = None) -> Path:
    """Resolve a MEDIA_ASSET.storage_ref (media/<slug>/photos/<id>.png) to an on-disk path (§6.3)."""
    root = Path(media_root) if media_root is not None else _DEFAULT_MEDIA_ROOT
    return root / asset.storage_ref.removeprefix("media/")


async def serve_photo_request(
    message: Message,
    db: AsyncSession,
    *,
    user_id: int,
    persona: Persona,
    request_text: str,
    context: dict,
    chat_client: ChatClient | None,
    gate: IntimacyGate,
    cfg: MediaDeliveryConfig = DEFAULT_CONFIG,
    media_root: str | Path | None = None,
) -> DeliveryResult:
    """Run F-012 delivery for one request and emit the result over Telegram (§3.6 Media path).

    Delivered → send the photo with its in-voice caption. Deflected/paced → send the in-voice line.
    Routed-to-gate → F-014 owns the response; this hook sends nothing. Returns the `DeliveryResult`
    so the caller can persist/audit the send."""
    result = await deliver_photo(
        db,
        user_id=user_id,
        persona=persona,
        request_text=request_text,
        context=context,
        caption_client=chat_client,
        gate=gate,
        cfg=cfg,
    )
    if result.delivered and result.asset is not None:
        path = asset_abspath(result.asset, media_root)
        if os.path.exists(path):
            await message.answer_photo(FSInputFile(str(path)), caption=result.caption or None)
        elif result.caption:
            # File vanished under us — never a broken-image placeholder; fall back to the line.
            await message.answer(result.caption)
    elif result.gate_result is not None:
        await _voice_gate_result(message, persona, result.gate_result, media_root)
    elif result.deflection:
        await message.answer(result.deflection)
    return result


# In-voice lines for the F-014 gate outcomes (integration wiring). Deliberately short and
# deterministic — the gate decides, she phrases it; RU/EN by persona language.
_GATE_LINES = {
    "ru": {
        "queued": "мм, дай мне чуть времени… сделаю кое-что специально для тебя 😏",
        "paced": "не всё сразу 😉 дай перевести дух",
        "not_adult": "сначала подтверди, что тебе 18+, без этого никак",
        "not_opted_in": "если хочешь такого — включи откровенный режим, я подожду 😉",
        "below_stage": "мы ещё не настолько близки… узнай меня получше 😊",
        "above_ceiling": "это слишком даже для меня 😅",
        "hard_safety": "нет. этого не будет.",
    },
    "en": {
        "queued": "mm, give me a little time… I'll make something just for you 😏",
        "paced": "not all at once 😉 let me catch my breath",
        "not_adult": "confirm you're 18+ first — can't skip that",
        "not_opted_in": "want that? turn on explicit mode, I'll wait 😉",
        "below_stage": "we're not that close yet… get to know me a little more 😊",
        "above_ceiling": "that's too much even for me 😅",
        "hard_safety": "no. that's not going to happen.",
    },
}


async def _voice_gate_result(
    message: Message, persona: Persona, gate_result, media_root=None
) -> None:
    """Turn F-014's (GateVerdict, FulfillResult) into exactly one user-visible reply: a delivered
    intimate asset goes out as a photo; every other outcome gets one short in-voice line."""
    lines = _GATE_LINES.get(getattr(persona, "language", "en"), _GATE_LINES["en"])
    try:
        verdict, fulfill = gate_result
    except (TypeError, ValueError):
        await message.answer(lines["paced"])
        return
    asset = getattr(fulfill, "asset", None)
    status = getattr(getattr(fulfill, "status", None), "value", "")
    if status == "delivered" and asset is not None:
        path = asset_abspath(asset, media_root)
        if os.path.exists(path):
            await message.answer_photo(FSInputFile(str(path)))
            return
        status = "queued"  # row without a live file — treat as not-ready
    reason = getattr(getattr(verdict, "reason", None), "value", "") or ""
    key = status if status in ("queued", "paced") else reason
    await message.answer(lines.get(key, lines["below_stage"]))
