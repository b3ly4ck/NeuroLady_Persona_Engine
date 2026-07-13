"""Vector index for user-fact semantic recall (F-004 vector half).

Wraps a Qdrant collection + an `Embedder`. A `USER_FACT` row and its vector point map 1:1 by using
the SQL `fact_id` as the Qdrant point id (FR-004-04). Every point payload carries `user_id`, and
**every search is filtered by `user_id`** so a query can never match another user's points
(FR-004-05/36, NFR-004-16 defense-in-depth). Any store/embed failure raises
`VectorStoreUnavailable` so callers degrade to keyword recall instead of breaking the turn
(FR-004-40 / NFR-004-07).

Dev uses Qdrant in embedded/local mode (a path or `:memory:`); production points at a Qdrant URL.
"""
from __future__ import annotations

import logging

from services.bot.domain.embeddings import Embedder

log = logging.getLogger(__name__)

COLLECTION = "user_facts"


class VectorStoreUnavailable(RuntimeError):
    """The vector store or embedder could not serve a request — caller should degrade."""


class MemoryIndex:
    def __init__(self, client, embedder: Embedder, collection: str = COLLECTION) -> None:
        self._client = client
        self._embedder = embedder
        self._collection = collection
        self._ready = False

    # ── collection lifecycle ─────────────────────────────────────────────────────────────────
    def _ensure_collection(self, dim: int) -> None:
        if self._ready:
            return
        from qdrant_client import models

        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                self._collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )
        self._ready = True

    # ── writes ───────────────────────────────────────────────────────────────────────────────
    def index_fact(self, user_id: int, fact_id: int, content: str) -> None:
        """Embed a fact and upsert its point (point id = fact_id). Raises on failure."""
        from qdrant_client import models

        try:
            vector = self._embedder.embed([content])[0]
            self._ensure_collection(len(vector))
            self._client.upsert(
                self._collection,
                points=[
                    models.PointStruct(
                        id=fact_id, vector=vector,
                        payload={"user_id": user_id, "fact_id": fact_id},
                    )
                ],
            )
        except Exception as exc:  # noqa: BLE001 - any backend failure → degrade
            raise VectorStoreUnavailable(str(exc)) from exc

    def remove_facts(self, fact_ids: list[int]) -> None:
        """Delete points for the given fact ids (used on supersede/delete). Raises on failure."""
        if not fact_ids:
            return
        try:
            if self._client.collection_exists(self._collection):
                self._client.delete(self._collection, points_selector=list(fact_ids))
        except Exception as exc:  # noqa: BLE001
            raise VectorStoreUnavailable(str(exc)) from exc

    # ── reads ────────────────────────────────────────────────────────────────────────────────
    def search(self, user_id: int, query: str, k: int) -> list[int]:
        """Return up to `k` fact ids most semantically similar to `query`, for THIS user only.

        The `user_id` filter is mandatory and always applied (NFR-004-16). Raises on failure so the
        caller can fall back to keyword recall.
        """
        from qdrant_client import models

        try:
            if not self._client.collection_exists(self._collection):
                return []
            vector = self._embedder.embed([query])[0]
            resp = self._client.query_points(
                self._collection,
                query=vector,
                query_filter=models.Filter(
                    must=[models.FieldCondition(
                        key="user_id", match=models.MatchValue(value=user_id))]
                ),
                limit=k,
            )
            return [int(p.id) for p in resp.points]
        except Exception as exc:  # noqa: BLE001
            raise VectorStoreUnavailable(str(exc)) from exc


def build_memory_index(location: str, model_name: str | None = None) -> MemoryIndex | None:
    """Build a MemoryIndex from config, or return None if the optional deps aren't installed
    (the memory system then degrades to keyword recall — FR-004-40).

    `location`: a Qdrant URL (http://…), a local directory path, or ":memory:".
    """
    try:
        from qdrant_client import QdrantClient

        from services.bot.domain.embeddings import DEFAULT_MODEL, FastEmbedEmbedder
    except ImportError:
        log.warning("semantic memory deps not installed — falling back to keyword recall")
        return None

    if location.startswith("http://") or location.startswith("https://"):
        client = QdrantClient(url=location)
    else:
        client = QdrantClient(path=location) if location != ":memory:" else QdrantClient(":memory:")
    embedder = FastEmbedEmbedder(model_name or DEFAULT_MODEL)
    return MemoryIndex(client, embedder)
