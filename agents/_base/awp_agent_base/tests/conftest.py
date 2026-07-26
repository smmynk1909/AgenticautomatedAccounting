from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from awp_mcp_base.uow import UnitOfWork
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.tables import metadata


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
def checkpoints(uow: UnitOfWork) -> CheckpointStore:
    return CheckpointStore(uow, dialect="sqlite")
