from typing import Any

import pytest
from awp_shared.auth import mint_user_jwt
from httpx import AsyncClient

from awp_gateway.tests.conftest import FakeMCP


def _headers(user_id: str, roles: list[str]) -> dict[str, str]:
    token = mint_user_jwt(user_id, roles)
    return {"Authorization": f"Bearer {token}"}


def _query_tickets_by_category(args: dict[str, Any]) -> dict[str, Any]:
    cat = args.get("category")
    return {"tickets": [{"category": cat}] if cat else []}


@pytest.mark.asyncio
async def test_support_lead_sees_all_categories_unfiltered(
    client: AsyncClient, mcp: FakeMCP
) -> None:
    mcp._handlers[("erp", "query_tickets")] = {"tickets": [{"category": "device"}]}
    r = await client.get("/api/tickets", headers=_headers("dev-support-lead", ["support_lead"]))
    assert r.status_code == 200
    assert mcp.calls == [("erp", "query_tickets", {"status": None, "priority": None})]


@pytest.mark.asyncio
async def test_finance_head_fans_out_across_own_categories(
    client: AsyncClient, mcp: FakeMCP
) -> None:
    mcp._handlers[("erp", "query_tickets")] = _query_tickets_by_category
    r = await client.get("/api/tickets", headers=_headers("dev-finance-head", ["finance_head"]))
    assert r.status_code == 200
    seen_categories = {c[2]["category"] for c in mcp.calls}
    assert seen_categories == {"payroll", "expense"}
    returned_categories = {t["category"] for t in r.json()["tickets"]}
    assert returned_categories == {"payroll", "expense"}


@pytest.mark.asyncio
async def test_finance_head_cannot_request_out_of_scope_category(client: AsyncClient) -> None:
    r = await client.get(
        "/api/tickets?category=hr", headers=_headers("dev-finance-head", ["finance_head"])
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_employee_gets_self_service_filter(client: AsyncClient, mcp: FakeMCP) -> None:
    mcp._handlers[("erp", "query_tickets")] = {"tickets": []}
    r = await client.get("/api/tickets", headers=_headers("dev-employee", ["employee"]))
    assert r.status_code == 200
    assert mcp.calls == [
        ("erp", "query_tickets", {"status": None, "priority": None, "requester_id": "dev-employee"})
    ]


@pytest.mark.asyncio
async def test_create_ticket_sets_requester_from_principal(
    client: AsyncClient, mcp: FakeMCP
) -> None:
    mcp._handlers[("erp", "create_ticket")] = {"ticket_id": "TKT-1"}
    r = await client.post(
        "/api/tickets",
        json={"channel": "chat", "category": "it_support", "subject": "x", "body": "y"},
        headers=_headers("dev-employee", ["employee"]),
    )
    assert r.status_code == 200
    _, _, args = mcp.calls[0]
    assert args["requester"] == {"type": "employee", "id": "dev-employee"}


@pytest.mark.asyncio
async def test_update_ticket_requires_nonempty_patch(client: AsyncClient) -> None:
    r = await client.patch(
        "/api/tickets/TKT-1", json={}, headers=_headers("dev-support-lead", ["support_lead"])
    )
    assert r.status_code == 400
