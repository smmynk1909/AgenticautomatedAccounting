from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from awp_mcp_audit.tables import metadata
from awp_mcp_base.uow import UnitOfWork


@pytest.fixture(autouse=True)
def _dev_auth_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWP_DEV_JWT_SECRET", "test-service-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_APPROVAL_JWT_SECRET", "test-approval-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_JWT_ISSUER", "awp-test")


@pytest.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    # StaticPool so every uow() connection shares the same in-memory DB — see
    # mcps/_base/awp_mcp_base/tests/conftest.py for the same pattern/rationale.
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
