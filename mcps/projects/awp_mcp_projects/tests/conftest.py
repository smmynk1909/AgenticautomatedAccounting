from collections.abc import AsyncIterator
from typing import Any

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditEvent
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from awp_mcp_projects.server import make_projects_server
from awp_mcp_projects.tables import metadata


class NullAuditSink:
    async def log_event(self, event: AuditEvent) -> None:
        pass


class FakeGiteaClient:
    """`GiteaClientLike` fake — a small fixed in-memory repo, no real HTTP."""

    def __init__(
        self,
        repos: list[dict[str, Any]] | None = None,
        files: dict[tuple[str, str], str] | None = None,
        diffs: dict[tuple[str, str, str], str] | None = None,
    ) -> None:
        self._repos = repos or []
        self._files = files or {}
        self._diffs = diffs or {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def list_repos(self) -> list[dict[str, Any]]:
        self.calls.append(("list_repos", ()))
        return self._repos

    async def get_file(self, repo: str, path: str, ref: str | None) -> dict[str, Any]:
        self.calls.append(("get_file", (repo, path, ref)))
        content = self._files[(repo, path)]
        return {"path": path, "sha": "fake-sha", "content": content}

    async def get_tree(self, repo: str, ref: str) -> list[dict[str, Any]]:
        self.calls.append(("get_tree", (repo, ref)))
        return [
            {"path": path, "type": "blob", "size": len(content)}
            for (r, path), content in self._files.items()
            if r == repo
        ]

    async def get_diff(self, repo: str, base: str, head: str) -> str:
        self.calls.append(("get_diff", (repo, base, head)))
        return self._diffs[(repo, base, head)]


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
def gitea() -> FakeGiteaClient:
    return FakeGiteaClient()


@pytest.fixture
def projects_server(
    uow: UnitOfWork, redis: FakeRedis, gitea: FakeGiteaClient
) -> AwpMcpServer:
    return make_projects_server(uow, redis, NullAuditSink(), gitea)
