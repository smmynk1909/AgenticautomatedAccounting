import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.audit_mw import AuditEvent
from fakeredis.aioredis import FakeRedis

from awp_mcp_docs.server import make_docs_server
from awp_mcp_docs.storage import DocStorage
from awp_mcp_docs.tests.fake_minio import FakeMinio

TEST_BUCKET = "test-docs-bucket"


class NullAuditSink:
    async def log_event(self, event: AuditEvent) -> None:
        pass


@pytest.fixture(autouse=True)
def _dev_auth_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWP_DEV_JWT_SECRET", "test-service-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_APPROVAL_JWT_SECRET", "test-approval-secret-32-bytes-min-xxxx")
    monkeypatch.setenv("AWP_JWT_ISSUER", "awp-test")


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture
def storage() -> DocStorage:
    doc_storage = DocStorage(FakeMinio(), TEST_BUCKET)  # type: ignore[arg-type]
    doc_storage.ensure_bucket()
    return doc_storage


@pytest.fixture
def docs_server(storage: DocStorage, redis: FakeRedis) -> AwpMcpServer:
    return make_docs_server(storage, redis, NullAuditSink())
