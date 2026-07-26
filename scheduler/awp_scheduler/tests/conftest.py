from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.tables import metadata
from awp_agent_orch0.intent_registry import IntentRegistry
from awp_mcp_base.uow import UnitOfWork
from awp_shared.bus import TaskBus
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool


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


@pytest.fixture(scope="session")
def registry() -> IntentRegistry:
    return IntentRegistry()


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture
def bus(redis: FakeRedis) -> TaskBus:
    return TaskBus(redis)


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
def checkpoints(sqlite_engine: AsyncEngine) -> CheckpointStore:
    return CheckpointStore(UnitOfWork(sqlite_engine), dialect="sqlite")
