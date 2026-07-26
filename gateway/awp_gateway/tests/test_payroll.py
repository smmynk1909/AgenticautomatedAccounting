import pytest
from awp_shared.auth import mint_user_jwt
from httpx import AsyncClient

from awp_gateway.tests.conftest import FakeMCP


def _headers(user_id: str, roles: list[str]) -> dict[str, str]:
    token = mint_user_jwt(user_id, roles)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_finance_head_can_view_payroll(client: AsyncClient, mcp: FakeMCP) -> None:
    mcp._handlers[("finance", "get_payroll_run")] = {"month": "2026-06", "status": "computed"}
    r = await client.get(
        "/api/payroll/runs/2026-06", headers=_headers("dev-finance-head", ["finance_head"])
    )
    assert r.status_code == 200
    assert mcp.calls == [("finance", "get_payroll_run", {"month": "2026-06"})]


@pytest.mark.asyncio
async def test_director_can_view_payroll(client: AsyncClient, mcp: FakeMCP) -> None:
    mcp._handlers[("finance", "get_payroll_run")] = {"month": "2026-06", "status": "computed"}
    r = await client.get(
        "/api/payroll/runs/2026-06", headers=_headers("dev-director", ["director"])
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_employee_cannot_view_payroll(client: AsyncClient) -> None:
    r = await client.get(
        "/api/payroll/runs/2026-06", headers=_headers("dev-employee", ["employee"])
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_payroll_requires_human_session(client: AsyncClient) -> None:
    r = await client.get("/api/payroll/runs/2026-06")
    assert r.status_code == 403
