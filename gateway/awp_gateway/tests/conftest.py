from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from awp_mcp_approvals.tables import metadata as approvals_metadata
from awp_mcp_base.uow import UnitOfWork
from awp_shared.bus import TaskBus
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from awp_gateway.app import create_app
from awp_gateway.deps import GatewayState


class FakeMCP:
    """`handlers`: `(server, tool) -> dict | Callable[[dict], dict]`. Missing
    handlers return `{}`."""

    def __init__(self, handlers: dict[tuple[str, str], Any] | None = None) -> None:
        self._handlers = handlers or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def call(self, server: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((server, tool, args))
        handler = self._handlers.get((server, tool))
        if handler is None:
            return {}
        result: dict[str, Any] = handler(args) if callable(handler) else handler
        return result


@pytest.fixture(autouse=True)
def _dev_auth_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWP_DEV_JWT_SECRET", "test-service-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_APPROVAL_JWT_SECRET", "test-approval-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_JWT_ISSUER", "awp-test")
    monkeypatch.setenv("AWP_ENV", "dev")


@pytest.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(approvals_metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def uow(sqlite_engine: AsyncEngine) -> UnitOfWork:
    return UnitOfWork(sqlite_engine)


@pytest.fixture
def mcp() -> FakeMCP:
    return FakeMCP()


@pytest.fixture
def bus() -> TaskBus:
    return TaskBus(FakeRedis(decode_responses=True))


@pytest.fixture
def state(mcp: FakeMCP, bus: TaskBus, uow: UnitOfWork) -> GatewayState:
    return GatewayState(mcp=mcp, bus=bus, uow=uow)  # type: ignore[arg-type]


@pytest.fixture
def app(state: GatewayState) -> FastAPI:
    return create_app(state)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
