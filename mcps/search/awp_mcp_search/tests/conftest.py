from __future__ import annotations

import zlib
from collections.abc import AsyncIterator

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditEvent
from fakeredis.aioredis import FakeRedis
from qdrant_client import AsyncQdrantClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from awp_mcp_search.qdrant_store import QdrantStore
from awp_mcp_search.server import make_search_server
from awp_mcp_search.tables import metadata

FAKE_DIM = 16


class FakeEmbedder:
    """Deterministic feature-hashed bag-of-words vector — real cosine
    similarity behavior for ranking tests without a live Ollama/bge-m3.
    Uses `zlib.crc32` (not `hash()`, which is salted per-process for `str`
    by default) so results are stable across test runs.
    """

    dim = FAKE_DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            v = [0.0] * self.dim
            for tok in text.lower().split():
                v[zlib.crc32(tok.encode()) % self.dim] += 1.0
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            vectors.append([x / norm for x in v])
        return vectors


class NullAuditSink:
    async def log_event(self, event: AuditEvent) -> None:
        pass


@pytest.fixture(autouse=True)
def _dev_auth_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWP_DEV_JWT_SECRET", "test-service-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_APPROVAL_JWT_SECRET", "test-approval-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_JWT_ISSUER", "awp-test")


@pytest.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def uow(sqlite_engine: AsyncEngine) -> UnitOfWork:
    return UnitOfWork(sqlite_engine)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def store() -> QdrantStore:
    return QdrantStore(AsyncQdrantClient(location=":memory:"), vector_size=FAKE_DIM)


@pytest.fixture
def search_server(
    uow: UnitOfWork, redis: FakeRedis, store: QdrantStore, embedder: FakeEmbedder
) -> AwpMcpServer:
    return make_search_server(uow, redis, NullAuditSink(), store, embedder)
