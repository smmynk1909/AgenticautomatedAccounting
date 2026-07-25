import uuid
from collections.abc import AsyncIterator
from datetime import date

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditEvent
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from awp_mcp_erp.server import make_erp_server
from awp_mcp_erp.tables import departments, metadata, roles, salary_bands


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
def erp_server(uow: UnitOfWork, redis: FakeRedis) -> AwpMcpServer:
    return make_erp_server(uow, redis, NullAuditSink())


@pytest.fixture
async def base_org(uow: UnitOfWork) -> dict[str, str]:
    """One department/role/salary_band — the minimum FK-satisfying scaffold
    every employee-touching test needs."""
    dept_id = str(uuid.uuid4())
    band_id = str(uuid.uuid4())
    role_id = str(uuid.uuid4())
    async with uow() as session:
        await session.execute(
            departments.insert().values(id=dept_id, name="Engineering", head_emp_id=None)
        )
        await session.execute(
            salary_bands.insert().values(
                id=band_id,
                grade="E2",
                min=700000,
                mid=1000000,
                max=1300000,
                currency="INR",
                effective_from=date(2025, 4, 1),
            )
        )
        await session.execute(
            roles.insert().values(
                id=role_id,
                title="Software Engineer (E2)",
                grade="E2",
                dept_id=dept_id,
                salary_band_id=band_id,
                role_profile={},
            )
        )
    return {"dept_id": dept_id, "role_id": role_id, "band_id": band_id}
