import pytest
from awp_mcp_approvals.store import ApprovalStore
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import mint_user_jwt
from httpx import AsyncClient


def _headers(user_id: str, roles: list[str]) -> dict[str, str]:
    token = mint_user_jwt(user_id, roles)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_inbox_filters_by_role(client: AsyncClient, uow: UnitOfWork) -> None:
    async with uow() as session:
        await ApprovalStore(session).create(
            gate="invoice_issue",
            payload={"x": 1},
            requested_by="FIN-1",
            approver_roles=["finance_head"],
            n_required=1,
            ttl_h=24,
        )
        await ApprovalStore(session).create(
            gate="shortlist_publish",
            payload={"x": 2},
            requested_by="HR-1",
            approver_roles=["recruiter"],
            n_required=1,
            ttl_h=24,
        )

    r = await client.get(
        "/api/approvals/inbox", headers=_headers("dev-finance-head", ["finance_head"])
    )
    assert r.status_code == 200
    gates = [a["gate"] for a in r.json()["approvals"]]
    assert gates == ["invoice_issue"]


@pytest.mark.asyncio
async def test_approve_mints_token_when_threshold_met(
    client: AsyncClient, uow: UnitOfWork
) -> None:
    async with uow() as session:
        created = await ApprovalStore(session).create(
            gate="invoice_issue",
            payload={"x": 1},
            requested_by="FIN-1",
            approver_roles=["finance_head"],
            n_required=1,
            ttl_h=24,
        )

    r = await client.post(
        f"/api/approvals/{created['id']}/approve",
        json={"comment": "looks good"},
        headers=_headers("dev-finance-head", ["finance_head"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert "token" in body


@pytest.mark.asyncio
async def test_approve_rejects_unauthorized_role(client: AsyncClient, uow: UnitOfWork) -> None:
    async with uow() as session:
        created = await ApprovalStore(session).create(
            gate="invoice_issue",
            payload={"x": 1},
            requested_by="FIN-1",
            approver_roles=["finance_head"],
            n_required=1,
            ttl_h=24,
        )

    r = await client.post(
        f"/api/approvals/{created['id']}/approve",
        json={},
        headers=_headers("dev-recruiter", ["recruiter"]),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reject_requires_reason(client: AsyncClient, uow: UnitOfWork) -> None:
    async with uow() as session:
        created = await ApprovalStore(session).create(
            gate="invoice_issue",
            payload={"x": 1},
            requested_by="FIN-1",
            approver_roles=["finance_head"],
            n_required=1,
            ttl_h=24,
        )

    r = await client.post(
        f"/api/approvals/{created['id']}/reject",
        json={},
        headers=_headers("dev-finance-head", ["finance_head"]),
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_reject_records_reason(client: AsyncClient, uow: UnitOfWork) -> None:
    async with uow() as session:
        created = await ApprovalStore(session).create(
            gate="invoice_issue",
            payload={"x": 1},
            requested_by="FIN-1",
            approver_roles=["finance_head"],
            n_required=1,
            ttl_h=24,
        )

    r = await client.post(
        f"/api/approvals/{created['id']}/reject",
        json={"reason": "amounts don't match"},
        headers=_headers("dev-finance-head", ["finance_head"]),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
