import pytest
from awp_shared.auth import mint_user_jwt
from httpx import AsyncClient

from awp_gateway.tests.conftest import FakeMCP


def _headers() -> dict[str, str]:
    token = mint_user_jwt("dev-employee", ["employee"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_task_proxies_to_erp(client: AsyncClient, mcp: FakeMCP) -> None:
    mcp._handlers[("erp", "get_task_status")] = {"task": {"status": "done"}}
    r = await client.get("/api/tasks/some-task-id", headers=_headers())
    assert r.status_code == 200
    assert r.json() == {"task": {"status": "done"}}
    assert mcp.calls == [("erp", "get_task_status", {"task_id": "some-task-id"})]


@pytest.mark.asyncio
async def test_get_task_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/api/tasks/some-task-id")
    assert r.status_code == 403
