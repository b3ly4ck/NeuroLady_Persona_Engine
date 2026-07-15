"""Authored initial biographies, keyed by persona name (F-006 FR-006-22).

Each entry is a `BiographySeed` imported at provisioning by `seed_biography`, giving the persona a
coherent past (and future) from her first message. Personas without an entry keep the thin
teaser-only identity until authored.
"""
from __future__ import annotations

from services.bot.domain.biography import BiographySeed

from .alina import ALINA

BIOGRAPHIES: dict[str, BiographySeed] = {
    "Alina": ALINA,
}
