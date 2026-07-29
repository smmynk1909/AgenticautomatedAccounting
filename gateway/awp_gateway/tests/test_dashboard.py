import pytest
from awp_shared.auth import mint_user_jwt
from httpx import AsyncClient

from awp_gateway.tests.conftest import FakeMCP


def _headers(user_id: str, roles: list[str]) -> dict[str, str]:
    token = mint_user_jwt(user_id, roles)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_own_role_dashboard_is_visible(client: AsyncClient, mcp: FakeMCP) -> None:
    mcp._handlers[("erp", "get_dashboard")] = {"items": [{"panel": "asset_register"}]}
    r = await client.get("/api/dashboard/manager", headers=_headers("dev-manager", ["manager"]))
    assert r.status_code == 200
    assert mcp.calls == [("erp", "get_dashboard", {"role": "manager"})]


@pytest.mark.asyncio
async def test_other_role_dashboard_is_forbidden(client: AsyncClient) -> None:
    r = await client.get("/api/dashboard/director", headers=_headers("dev-manager", ["manager"]))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_director_can_view_any_dashboard(client: AsyncClient, mcp: FakeMCP) -> None:
    mcp._handlers[("erp", "get_dashboard")] = {"items": []}
    r = await client.get("/api/dashboard/manager", headers=_headers("dev-director", ["director"]))
    assert r.status_code == 200
    assert mcp.calls == [("erp", "get_dashboard", {"role": "manager"})]


@pytest.mark.asyncio
async def test_ceo_can_view_any_dashboard(client: AsyncClient, mcp: FakeMCP) -> None:
    mcp._handlers[("erp", "get_dashboard")] = {"items": []}
    r = await client.get("/api/dashboard/admin_head", headers=_headers("dev-ceo", ["ceo"]))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_requires_human_session(client: AsyncClient) -> None:
    r = await client.get("/api/dashboard/manager")
    assert r.status_code == 403
