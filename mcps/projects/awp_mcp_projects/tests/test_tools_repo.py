import pytest
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError
from fakeredis.aioredis import FakeRedis

from awp_mcp_projects.server import make_projects_server
from awp_mcp_projects.tests.conftest import FakeGiteaClient, NullAuditSink


def _headers() -> dict[str, str]:
    token = mint_service_jwt("OPS-1", ["projects.read", "projects.write"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_repos_returns_slugs(uow: UnitOfWork, redis: FakeRedis) -> None:
    gitea = FakeGiteaClient(
        repos=[{"full_name": "awp-admin/svc-a", "description": "x", "default_branch": "main"}]
    )
    server = make_projects_server(uow, redis, NullAuditSink(), gitea)
    result = await server.dispatch_raw("list_repos", {}, _headers())
    assert result["repos"] == [
        {"slug": "awp-admin/svc-a", "description": "x", "default_branch": "main"}
    ]


@pytest.mark.asyncio
async def test_get_file_decodes_content(uow: UnitOfWork, redis: FakeRedis) -> None:
    gitea = FakeGiteaClient(
        files={("awp-admin/svc-a", "mathutils.py"): "def add(a, b):\n    return a + b\n"}
    )
    server = make_projects_server(uow, redis, NullAuditSink(), gitea)
    result = await server.dispatch_raw(
        "get_file", {"repo": "awp-admin/svc-a", "path": "mathutils.py"}, _headers()
    )
    assert "def add" in result["content"]


@pytest.mark.asyncio
async def test_get_file_requires_fields(uow: UnitOfWork, redis: FakeRedis) -> None:
    server = make_projects_server(uow, redis, NullAuditSink(), FakeGiteaClient())
    with pytest.raises(ValidationError):
        await server.dispatch_raw("get_file", {"repo": "x"}, _headers())


@pytest.mark.asyncio
async def test_get_diff_returns_diff_text(uow: UnitOfWork, redis: FakeRedis) -> None:
    gitea = FakeGiteaClient(diffs={("awp-admin/svc-a", "main", "feature"): "diff --git a/x b/x\n"})
    server = make_projects_server(uow, redis, NullAuditSink(), gitea)
    result = await server.dispatch_raw(
        "get_diff", {"repo": "awp-admin/svc-a", "base": "main", "head": "feature"}, _headers()
    )
    assert result["diff"] == "diff --git a/x b/x\n"


@pytest.mark.asyncio
async def test_index_repo_chunks_every_file(uow: UnitOfWork, redis: FakeRedis) -> None:
    gitea = FakeGiteaClient(
        files={
            ("awp-admin/svc-a", "a.py"): "print('a')\n",
            ("awp-admin/svc-a", "b.py"): "print('b')\n",
        }
    )
    server = make_projects_server(uow, redis, NullAuditSink(), gitea)
    result = await server.dispatch_raw(
        "index_repo", {"repo": "awp-admin/svc-a", "ref": "main"}, _headers()
    )
    assert result["files_indexed"] == 2
    paths = {c["path"] for c in result["chunks"]}
    assert paths == {"a.py", "b.py"}


@pytest.mark.asyncio
async def test_index_repo_skips_binary_extensions(uow: UnitOfWork, redis: FakeRedis) -> None:
    gitea = FakeGiteaClient()
    # get_tree is the only call that needs the binary entry present; skip
    # via the raw tree shape directly since FakeGiteaClient derives tree
    # entries from `files`, and a real image wouldn't decode as text.
    gitea._files[("awp-admin/svc-a", "logo.png")] = "not-real-binary-but-should-be-skipped"
    gitea._files[("awp-admin/svc-a", "a.py")] = "print('a')\n"
    server = make_projects_server(uow, redis, NullAuditSink(), gitea)
    result = await server.dispatch_raw(
        "index_repo", {"repo": "awp-admin/svc-a", "ref": "main"}, _headers()
    )
    assert result["files_indexed"] == 1
    assert {c["path"] for c in result["chunks"]} == {"a.py"}


@pytest.mark.asyncio
async def test_ci_status_reports_not_configured(uow: UnitOfWork, redis: FakeRedis) -> None:
    server = make_projects_server(uow, redis, NullAuditSink(), FakeGiteaClient())
    result = await server.dispatch_raw("ci_status", {"repo": "awp-admin/svc-a"}, _headers())
    assert result["status"] == "not_configured"
