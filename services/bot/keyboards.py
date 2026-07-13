"""Inline and reply keyboards for the onboarding screens (architecture.md §1.2).

**No main menu, ever** (architecture.md §1.3 — removed by explicit product decision): the reply
keyboard carries exactly one persistent action, "💋 Choose Lady".

Callback-data scheme (kept tiny and explicit):
- ``card:<index>``          — show the gallery card at <index> (used by ◀/▶ pagination)
- ``startchat:<persona_id>``— Start Chat with a persona
- ``noop``                  — inert (the counter button)
"""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from services.bot.domain.gallery import counter_label, cyclic_index
from services.bot.i18n import t


def card_kb(persona_id: int, index: int, total: int, locale: str) -> InlineKeyboardMarkup:
    """FR-001-05/06/09 — ◀ counter ▶ pagination row + a 'Start Chat' button.

    The ◀/▶ buttons carry the *resulting* (cyclically wrapped) index so navigation can never
    desync from the counter (NFR-001-10).
    """
    prev_idx = cyclic_index(index, -1, total)
    next_idx = cyclic_index(index, +1, total)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀", callback_data=f"card:{prev_idx}"),
                InlineKeyboardButton(text=counter_label(index, total), callback_data="noop"),
                InlineKeyboardButton(text="▶", callback_data=f"card:{next_idx}"),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_start_chat", locale), callback_data=f"startchat:{persona_id}"
                )
            ],
        ]
    )


def reply_kb(locale: str) -> ReplyKeyboardMarkup:
    """FR-001-12 — persistent reply keyboard: a single '💋 Choose Lady' button. No menu."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("btn_choose_lady", locale))]],
        resize_keyboard=True,
        is_persistent=True,
    )
