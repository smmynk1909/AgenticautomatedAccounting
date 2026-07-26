from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.tables import metadata
from awp_mcp_base.uow import UnitOfWork
from awp_shared.bus import TaskBus
from awp_shared.llm import LLMResponse
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from awp_agent_orch0.intent_registry import IntentRegistry


class FakeLLM:
    """`responses`: scripted `LLMResponse`s, one per expected `chat()` call
    in call order; the last one repeats if `chat()` is called more times
    than scripted (handy for re-plan loops)."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls.append({"messages": messages, **kwargs})
        if not self._responses:
            raise AssertionError("FakeLLM.chat called with no scripted response left")
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


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
def bus() -> TaskBus:
    return TaskBus(FakeRedis(decode_responses=True))


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
