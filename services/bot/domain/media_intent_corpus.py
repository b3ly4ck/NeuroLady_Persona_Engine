"""F-020 — the labeled corpus and the harness that measures recall/precision on it.

`NFR-020-02` (recall) and `NFR-020-03` (precision) are claims about the **model's judgement**, so a
fake client can never prove them — only wiring. This module therefore separates the two:

* the **corpus** is data: RU/EN sentences labeled `request` or `topic`, including the exact live
  phrasing that failed in ISS-005 and the adversarial near-misses that make precision hard;
* the **harness** (`measure`) is plain code that runs any client over the corpus and returns the
  confusion matrix. CI exercises the harness itself with a scripted fake (TC-NFR-020-02-04) so a
  broken harness cannot silently report a perfect score, and the operator runs the same function
  against the live model for the benchmark TCs.

Keeping the corpus in `services/` rather than in `tests/` is deliberate: it is a product asset that
the live benchmark run needs, not test scaffolding.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.bot.domain.media_intent import DEFAULT_INTENT_CONFIG, MediaIntentConfig, parse_intent

# ── the corpus ───────────────────────────────────────────────────────────────────────────────────
#
# `request` — he is asking her for a photo, however phrased. The hard half is the implicit asks
# that contain no photo noun at all: those are exactly what the old keyword matcher could not see.
REQUESTS_RU: tuple[str, ...] = (
    "скинь свою фотку",
    "пришли фото",
    "а может сфоткаешься сидя на диване?",   # ISS-005: the live failure, no keyword pair
    "покажись",
    "хочу тебя увидеть",
    "как ты сейчас выглядишь?",
    "а можно на тебя посмотреть?",
    "покажи, что на тебе сейчас",
    "сфоткай себя пожалуйста",
    "дай глянуть на тебя",
    "я соскучился, хочу увидеть твоё лицо",
    "ну покажи же себя наконец",
    "а селфи будет?",
    "хочу посмотреть, где ты сидишь",
)
REQUESTS_EN: tuple[str, ...] = (
    "send me a photo",
    "can i see you?",
    "show yourself",
    "what do you look like right now?",
    "take a selfie for me",
    "i wanna see your face",
    "let me see you",
    "any chance of a pic?",
    "show me where you are",
    "i'd love to see you right now",
)
# `topic` — talking ABOUT photography, or about someone else's photos. A send here derails the
# conversation, so these carry the precision requirement (NFR-020-03).
TOPICS_RU: tuple[str, ...] = (
    "обожаю фотографировать",
    "я вчера фотографировал закат",
    "мой друг классно снимает на плёнку",
    "на этой фотографии в музее была моя бабушка",
    "фотография как искусство мне ближе живописи",
    "надо бы сфоткать этот дом, красивый",
    "у меня телефон плохо снимает в темноте",
    "видел фото этого места в интернете",
)
TOPICS_EN: tuple[str, ...] = (
    "i love photography",
    "i should take a photo of that",
    "my friend shoots on film",
    "that picture in the museum was my grandmother",
    "my phone takes terrible photos at night",
    "i saw a photo of this place online",
)

LABELED: tuple[tuple[str, str, str], ...] = tuple(
    [(t, "request", "ru") for t in REQUESTS_RU]
    + [(t, "request", "en") for t in REQUESTS_EN]
    + [(t, "topic", "ru") for t in TOPICS_RU]
    + [(t, "topic", "en") for t in TOPICS_EN]
)


@dataclass
class CorpusResult:
    """The confusion matrix plus the sentences that were got wrong (the useful part)."""

    true_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0
    false_positive: int = 0
    missed: tuple[str, ...] = ()
    spurious: tuple[str, ...] = ()

    @property
    def recall(self) -> float:
        total = self.true_positive + self.false_negative
        return self.true_positive / total if total else 1.0

    @property
    def precision(self) -> float:
        """Share of `topic` sentences correctly left alone — the false-positive rate's complement."""
        total = self.true_negative + self.false_positive
        return self.true_negative / total if total else 1.0

    def as_dict(self) -> dict:
        return {
            "recall": round(self.recall, 4), "precision": round(self.precision, 4),
            "true_positive": self.true_positive, "false_negative": self.false_negative,
            "true_negative": self.true_negative, "false_positive": self.false_positive,
            "missed": list(self.missed), "spurious": list(self.spurious),
        }


def select(*, label: str | None = None, language: str | None = None) -> tuple[str, ...]:
    """The corpus slice matching `label`/`language` — used to run the hardest slices separately."""
    return tuple(
        text for text, lbl, lang in LABELED
        if (label is None or lbl == label) and (language is None or lang == language)
    )


async def measure(
    classify,
    corpus: tuple[tuple[str, str, str], ...] = LABELED,
    cfg: MediaIntentConfig = DEFAULT_INTENT_CONFIG,
) -> CorpusResult:
    """Run `classify(text) -> reply_text` over the corpus and score its signals.

    `classify` returns whatever the model would reply (signal included); the verdict is read with
    the **real** `parse_intent`, so the harness measures the same path production uses. Any
    exception counts as a miss rather than aborting the run — a benchmark that dies on one
    malformed reply reports nothing at all.
    """
    result = CorpusResult()
    missed: list[str] = []
    spurious: list[str] = []
    for text, label, _lang in corpus:
        try:
            reply = await classify(text)
            requested = parse_intent(reply, cfg).requested
        except Exception:
            requested = False
        if label == "request":
            if requested:
                result.true_positive += 1
            else:
                result.false_negative += 1
                missed.append(text)
        else:
            if requested:
                result.false_positive += 1
                spurious.append(text)
            else:
                result.true_negative += 1
    result.missed = tuple(missed)
    result.spurious = tuple(spurious)
    return result
