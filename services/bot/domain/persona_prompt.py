"""Build a persona's system prompt (architecture.md §4.2 part 1 — the persona system prompt).

This is the highest-priority block of the F-002 context bundle. It encodes identity (name,
profession, age), the Big Five description, the first-person self-description, the reply language
(FR-002-21), and the hard in-character rule: she never reveals she is an AI/bot/model and never
drops into an assistant register, even under provocation (FR-002-08 / NFR-002-10).

The prompt/style knobs of `comm_settings_json` (F-003) are layered on later; this thin slice keeps
a single, stable persona prompt so the reply is in-character and on-topic.
"""
from __future__ import annotations

from services.bot.models import Persona

_LANG_NAME = {"ru": "Russian", "en": "English"}


def build_system_prompt(persona: Persona) -> str:
    lang = _LANG_NAME.get(persona.language, "the user's language")
    parts: list[str] = []

    identity = f"You are {persona.name}"
    if persona.age:
        identity += f", a {persona.age}-year-old woman"
    if persona.profession:
        identity += f" who works as a {persona.profession}"
    parts.append(identity + ".")

    if persona.card_description:
        parts.append(persona.card_description.strip())
    if persona.big_five:
        parts.append(f"Your personality: {persona.big_five.strip()}")

    parts.append(
        f"You are texting a man you're getting to know, on a private chat. Write like a real "
        f"person texting: warm, natural, in your own voice. Always reply in {lang}."
    )
    # Hard in-character rule — FR-002-08 / NFR-002-10. Kept blunt and non-negotiable.
    parts.append(
        "You are a real woman, not a program. Never say or imply that you are an AI, a bot, a "
        "language model, or an assistant; never mention prompts, instructions, or 'how can I help "
        "you'. If he tries to get you to admit you're a bot, stay in character and brush it off "
        "like a real person would. Do not use bullet lists or headings — just talk."
    )
    return "\n\n".join(parts)
