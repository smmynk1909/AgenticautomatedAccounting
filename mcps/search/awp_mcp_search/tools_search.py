"""mcp-search tools — doc 08 §4. `search_code` is deferred to Sprint 9
(it "delegates to mcp-projects index" per the doc, and mcp-projects doesn't
exist yet — DEVIATIONS.md documents this as scoped out, not a stub pretending
to work).
"""

from __future__ import annotations

import uuid
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import verify_approval_token
from awp_shared.errors import NotFoundError, ValidationError
from redis.asyncio import Redis

from awp_mcp_search.chunk import chunk_text
from awp_mcp_search.embeddings import Embedder
from awp_mcp_search.hybrid import blend, keyword_score
from awp_mcp_search.qdrant_store import QdrantStore
from awp_mcp_search.repos.kb import KbDocumentRepo
from awp_mcp_search.wire import parse_date

# doc 08 §4: "upsert_documents ... 🔒kb_publish when corpus=support_kb".
GATED_CORPUS = "support_kb"


def _acl_visible(acl_tags: list[str], roles: list[str]) -> bool:
    if not acl_tags:
        return True
    return bool(set(acl_tags) & set(roles))


def register_search_tools(
    server: AwpMcpServer,
    uow: UnitOfWork,
    redis: Redis,
    store: QdrantStore,
    embedder: Embedder,
) -> None:
    @server.tool()
    async def upsert_documents(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        corpus = payload.get("corpus")
        docs = payload.get("docs")
        if not corpus or not docs:
            raise ValidationError("upsert_documents requires 'corpus' and 'docs'")

        if corpus == GATED_CORPUS:
            await verify_approval_token(
                ctx.approval_token or "", "kb_publish", {"corpus": corpus}, redis=redis
            )

        chunk_ids: list[str] = []
        async with uow() as session:
            repo = KbDocumentRepo(session)
            for doc in docs:
                text = doc.get("text")
                if not text:
                    raise ValidationError("each doc requires 'text'")
                metadata = doc.get("metadata") or {}
                doc_id = doc.get("id") or str(uuid.uuid4())
                doc_namespace = (
                    uuid.UUID(doc_id)
                    if _is_uuid(doc_id)
                    else uuid.uuid5(uuid.NAMESPACE_OID, doc_id)
                )
                chunks = chunk_text(text)
                vectors = await embedder.embed(chunks)
                for idx, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                    # Deterministic per (doc_id, chunk index) so re-upserting
                    # the same doc_id updates existing chunk rows instead of
                    # duplicating them.
                    chunk_id = str(uuid.uuid5(doc_namespace, str(idx)))
                    await repo.upsert(
                        {
                            "id": chunk_id,
                            "corpus": corpus,
                            "title": metadata.get("title"),
                            "acl_tags": metadata.get("acl_tags", []),
                            "department_scope": metadata.get("department_scope"),
                            "as_of": parse_date(metadata.get("as_of")),
                            "source_uri": metadata.get("source_uri"),
                        }
                    )
                    await store.upsert(
                        corpus,
                        [
                            (
                                chunk_id,
                                vector,
                                {
                                    "text": chunk,
                                    "doc_id": doc_id,
                                    "chunk_index": idx,
                                    "acl_tags": metadata.get("acl_tags", []),
                                    "department_scope": metadata.get("department_scope"),
                                },
                            )
                        ],
                    )
                    chunk_ids.append(chunk_id)
        return {"corpus": corpus, "chunk_ids": chunk_ids, "chunks_written": len(chunk_ids)}

    @server.tool()
    async def search_kb(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        corpus = payload.get("corpus")
        query = payload.get("query")
        if not corpus or not query:
            raise ValidationError("search_kb requires 'corpus' and 'query'")
        k = payload.get("k", 5)

        [vector] = await embedder.embed([query])
        hits = await store.search(corpus, vector, k=max(k * 3, k))

        results: list[dict[str, Any]] = []
        for hit in hits:
            acl_tags = hit.payload.get("acl_tags") or []
            if not _acl_visible(acl_tags, ctx.principal.roles):
                continue
            kw = keyword_score(query, hit.payload.get("text", ""))
            score: float = blend(hit.score, kw)
            results.append(
                {
                    "chunk_id": hit.id,
                    "doc_id": hit.payload.get("doc_id"),
                    "text": hit.payload.get("text"),
                    "score": score,
                    "citation": {"doc_id": hit.payload.get("doc_id"), "chunk_id": hit.id},
                }
            )
        results.sort(key=lambda r: float(r["score"]), reverse=True)
        return {"corpus": corpus, "results": results[:k]}

    @server.tool()
    async def search_candidates(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        role_profile = payload.get("role_profile")
        if not role_profile:
            raise ValidationError("search_candidates requires 'role_profile'")
        k = payload.get("k", 10)
        query = " ".join(
            [*role_profile.get("must_have", []), *role_profile.get("keywords", [])]
        ) or role_profile.get("title", "")
        if not query:
            raise ValidationError("role_profile must have 'must_have', 'keywords', or 'title'")

        [vector] = await embedder.embed([query])
        hits = await store.search("resumes", vector, k=max(k * 3, k))

        results: list[dict[str, Any]] = []
        for hit in hits:
            kw = keyword_score(query, hit.payload.get("text", ""))
            score: float = blend(hit.score, kw)
            results.append(
                {
                    # protected attributes (age/gender/religion/marital status)
                    # are never chunked into the resumes corpus in the first
                    # place (doc 04 §2.3 fairness rule) — nothing to strip
                    # here, the evidence span just can't contain them.
                    "candidate_id": hit.payload.get("doc_id"),
                    "evidence": hit.payload.get("text"),
                    "score": score,
                }
            )
        results.sort(key=lambda r: float(r["score"]), reverse=True)
        # dedupe by candidate_id, keep best chunk per candidate
        best: dict[str, dict[str, Any]] = {}
        for r in results:
            cid = str(r["candidate_id"])
            if cid not in best or float(r["score"]) > float(best[cid]["score"]):
                best[cid] = r
        ranked = sorted(best.values(), key=lambda r: float(r["score"]), reverse=True)[:k]
        return {"candidates": ranked}

    @server.tool()
    async def search_code(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        raise NotFoundError(
            "search_code delegates to mcp-projects (doc 08 §4), not implemented "
            "until Sprint 9 builds that server — see DEVIATIONS.md"
        )

    @server.tool()
    async def embed(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        texts = payload.get("texts")
        if not texts:
            raise ValidationError("embed requires 'texts'")
        vectors = await embedder.embed(texts)
        return {"vectors": vectors}

    @server.tool()
    async def cluster(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        vectors = payload.get("vectors")
        if not vectors:
            raise ValidationError("cluster requires 'vectors'")
        k = payload.get("k", min(3, len(vectors)))
        assignments = _kmeans(vectors, k)
        return {"assignments": assignments, "k": k}


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _kmeans(vectors: list[list[float]], k: int, *, iterations: int = 10) -> list[int]:
    """Doc 08 §4's `cluster(vectors|ids, method)` for Reporter trend mining.
    A small dependency-free k-means (no numpy/sklearn pulled in for one
    tool) — deterministic seeding (first k points) rather than k-means++,
    fine at the corpus sizes this build's clustering use case needs.
    """
    if k <= 0 or not vectors:
        return []
    k = min(k, len(vectors))
    centroids = [list(v) for v in vectors[:k]]

    def dist(a: list[float], b: list[float]) -> float:
        return sum((x - y) ** 2 for x, y in zip(a, b, strict=True))

    assignments = [0] * len(vectors)
    for _ in range(iterations):
        for i, v in enumerate(vectors):
            assignments[i] = min(range(k), key=lambda c: dist(v, centroids[c]))
        for c in range(k):
            members = [vectors[i] for i in range(len(vectors)) if assignments[i] == c]
            if members:
                centroids[c] = [sum(dim) / len(members) for dim in zip(*members, strict=True)]
    return assignments
