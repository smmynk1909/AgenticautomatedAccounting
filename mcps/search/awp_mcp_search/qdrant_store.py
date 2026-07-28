"""Thin wrapper over `qdrant_client.AsyncQdrantClient` — doc 08 §4's
"Qdrant collections: resumes, support_kb, fin_kb, project_docs, eng_kb,
market_intel, code_{project}" (doc 09 §1). One Qdrant collection per corpus,
created lazily on first write. Point ids are `kb_documents.id` (a real UUID
string — Qdrant only accepts UUID or unsigned-int point ids), so a search
hit maps straight back to its Postgres metadata row.

Tests point this at `AsyncQdrantClient(location=":memory:")` — the
in-process local-mode backend the qdrant-client package ships for exactly
this purpose, so unit tests don't need a running Qdrant container.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models

VECTOR_SIZE = 1024  # bge-m3's embedding dimension


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    payload: dict[str, Any]


class QdrantStore:
    def __init__(self, client: AsyncQdrantClient, *, vector_size: int = VECTOR_SIZE) -> None:
        self._client = client
        self._vector_size = vector_size
        self._ensured: set[str] = set()

    async def ensure_collection(self, collection: str) -> None:
        if collection in self._ensured:
            return
        if not await self._client.collection_exists(collection):
            await self._client.create_collection(
                collection,
                vectors_config=models.VectorParams(
                    size=self._vector_size, distance=models.Distance.COSINE
                ),
            )
        self._ensured.add(collection)

    async def upsert(
        self, collection: str, points: list[tuple[str, list[float], dict[str, Any]]]
    ) -> None:
        await self.ensure_collection(collection)
        await self._client.upsert(
            collection,
            points=[
                models.PointStruct(id=pid, vector=vector, payload=payload)
                for pid, vector, payload in points
            ],
        )

    async def search(
        self,
        collection: str,
        vector: list[float],
        *,
        k: int,
        query_filter: models.Filter | None = None,
    ) -> list[SearchHit]:
        await self.ensure_collection(collection)
        result = await self._client.query_points(
            collection, query=vector, limit=k, query_filter=query_filter, with_payload=True
        )
        return [
            SearchHit(id=str(p.id), score=p.score, payload=p.payload or {}) for p in result.points
        ]
