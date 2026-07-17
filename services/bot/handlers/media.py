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
    elif result.deflection:
        await message.answer(result.deflection)
    return result
