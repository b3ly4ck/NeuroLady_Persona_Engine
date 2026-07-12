"""Inline and reply keyboards for the onboarding screens (architecture.md §1.2).

Callback-data scheme (kept tiny and explicit):
- ``start``                 — Welcome "Start" -> open gallery at card 0
- ``card:<index>``          — show the gallery card at <index> (used by ◀/▶ pagination)
- ``startchat:<persona_id>``— Start Chat with a persona
- ``choose_lady`` / ``menu`` / ``resume`` — menu navigation
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


def welcome_kb(locale: str) -> InlineKeyboardMarkup:
    """FR-001-02 — a single full-width 'Start' inline button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t("btn_start", locale), callback_data="start")]]
    )


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
    """FR-001-12 — persistent reply keyboard: '💋 Choose Lady' + a menu (≡) button."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_choose_lady", locale))],
            [KeyboardButton(text=t("btn_menu", locale))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def menu_kb(locale: str) -> InlineKeyboardMarkup:
    """FR-001-16 — main menu: at least 'Choose Lady' and 'Resume chat', one tap each."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_choose_lady", locale), callback_data="choose_lady")],
            [InlineKeyboardButton(text=t("btn_resume", locale), callback_data="resume")],
        ]
    )
