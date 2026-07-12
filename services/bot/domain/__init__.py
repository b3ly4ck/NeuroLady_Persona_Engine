"""Pure domain logic for onboarding (F-001), independent of Telegram/aiogram.

Everything here operates on an `AsyncSession` and plain values, so it is fully unit/integration
testable without a running bot. The aiogram handlers call into these functions.
"""
