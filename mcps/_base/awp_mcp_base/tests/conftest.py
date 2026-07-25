from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

widgets_metadata = MetaData()
widgets_table = Table(
    "widgets",
    widgets_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False),
    Column("updated_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),
)


@pytest.fixture(autouse=True)
def _dev_auth_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWP_DEV_JWT_SECRET", "test-service-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_APPROVAL_JWT_SECRET", "test-approval-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_JWT_ISSUER", "awp-test")


@pytest.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    # StaticPool: aiosqlite's `:memory:` DB is per-connection by default, which
    # breaks multi-session tests (uow() opens a fresh connection per call).
    # Real deployments always use postgresql+asyncpg (see uow.make_engine) —
    # this wiring is test-only.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(widgets_metadata.create_all)
    yield engine
    await engine.dispose()
