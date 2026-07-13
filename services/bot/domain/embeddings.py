"""Text embedding for semantic memory (F-004 vector half).

A small, multilingual (RU+EN) embedding model runs locally on CPU via `fastembed` (ONNX — no
torch, no GPU contention with the chat model). Kept behind an `Embedder` protocol so tests can
inject a deterministic fake and production can swap the model by config (architecture.md §6.2c:
models are pluggable behind an interface).

Optional dependency: if `fastembed` isn't installed, the memory system degrades to keyword recall
(FR-004-40) — nothing here is imported at module load of the bot.
"""
from __future__ import annotations

from typing import Protocol

# Default: 384-dim multilingual MiniLM — small/fast, solid RU+EN semantic quality. Swap via
# EMBED_MODEL (e.g. intfloat/multilingual-e5-large for higher quality at ~2 GB).
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one dense vector per input text."""
        ...


class FastEmbedEmbedder:
    """`fastembed`-backed embedder. The model is lazy-loaded (downloaded) on first use."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._model = None  # loaded on first embed

    def _ensure(self):
        if self._model is None:
            from fastembed import TextEmbedding  # imported lazily (optional dep)

            self._model = TextEmbedding(model_name=self._model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure()
        return [vec.tolist() for vec in model.embed(list(texts))]
