"""services.bot — the Telegram bot application.

Implements feature **F-001 — Onboarding & Persona Selection** (see
`developer files/features/F-001-onboarding-persona-selection.md`): `/start` -> directly to
"Choose Lady" carousel -> Start Chat -> video-note intro -> ready chat.

Layered so the domain logic (`services.bot.domain`) is pure and testable without Telegram; the
aiogram handlers (`services.bot.handlers`) are a thin I/O layer on top (architecture.md §3.1/§3.2).
"""
