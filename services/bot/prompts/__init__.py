"""Versioned prompt assets (architecture.md §4.6/§4.8 — prompts are per-module, versioned files,
never hard-coded inline). Loaded by id so a prompt can be revised without touching service code.
"""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a versioned prompt asset by file stem (e.g. 'relationship_reflection_v1')."""
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8")
