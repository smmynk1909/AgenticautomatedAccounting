from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditEvent
from fakeredis.aioredis import FakeRedis
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from awp_mcp_finance.server import make_finance_server
from awp_mcp_finance.tables import accounts, metadata, periods

SEED_ACCOUNTS = [
    {"code": "1001", "name": "Bank", "type": "asset"},
    {"code": "1002", "name": "Accounts Receivable", "type": "asset"},
    {"code": "1005", "name": "Accumulated Depreciation", "type": "asset"},
    {"code": "1006", "name": "GST Input Credit", "type": "asset"},
    {"code": "2001", "name": "Accounts Payable", "type": "liability"},
    {"code": "2002", "name": "Salary Payable", "type": "liability"},
    {"code": "2007", "name": "GST Output Liability", "type": "liability"},
    {"code": "3001", "name": "Share Capital", "type": "equity"},
    {"code": "4001", "name": "Domestic Services Income", "type": "income"},
    {"code": "5001", "name": "Salaries Expense", "type": "expense"},
    {"code": "5008", "name": "Depreciation Expense", "type": "expense"},
]
SEED_PERIODS = ["2026-05", "2026-06"]


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
        now = datetime.now(UTC)
        await conn.execute(
            insert(accounts),
            [{"created_at": now, "updated_at": now, **row} for row in SEED_ACCOUNTS],
        )
        await conn.execute(
            insert(periods),
            [
                {"period": p, "status": "open", "created_at": now, "updated_at": now}
                for p in SEED_PERIODS
            ],
        )
    yield engine
    await engine.dispose()


@pytest.fixture
def uow(sqlite_engine: AsyncEngine) -> UnitOfWork:
    return UnitOfWork(sqlite_engine)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture
def finance_server(uow: UnitOfWork, redis: FakeRedis) -> AwpMcpServer:
    return make_finance_server(uow, redis, NullAuditSink())
