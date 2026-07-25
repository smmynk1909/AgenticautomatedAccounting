import pytest
from awp_mcp_base.uow import UnitOfWork

from awp_mcp_approvals.store import ApprovalStore


@pytest.mark.asyncio
async def test_create_and_get_round_trip(uow: UnitOfWork) -> None:
    async with uow() as session:
        store = ApprovalStore(session)
        created = await store.create(
            gate="invoice_issue",
            payload={"invoice_id": "INV-1"},
            requested_by="FIN-1",
            approver_roles=["finance_head"],
            n_required=1,
            ttl_h=24,
        )
    async with uow() as session:
        fetched = await ApprovalStore(session).get(created["id"])
    assert fetched is not None
    assert fetched["status"] == "pending"
    assert fetched["payload"] == {"invoice_id": "INV-1"}


@pytest.mark.asyncio
async def test_record_vote_accumulates(uow: UnitOfWork) -> None:
    async with uow() as session:
        store = ApprovalStore(session)
        created = await store.create(
            gate="payroll_run",
            payload={"register_id": "r1"},
            requested_by="FIN-1",
            approver_roles=["finance_head", "director"],
            n_required=2,
            ttl_h=24,
        )
        await store.record_vote(created["id"], "dev-finance-head", "looks good")
        updated = await store.record_vote(created["id"], "dev-director", "approved")

    assert len(updated["approvals_received"]) == 2
    assert {v["user_id"] for v in updated["approvals_received"]} == {
        "dev-finance-head",
        "dev-director",
    }


@pytest.mark.asyncio
async def test_mark_expired_if_due_transitions_status(uow: UnitOfWork) -> None:
    async with uow() as session:
        store = ApprovalStore(session)
        created = await store.create(
            gate="invoice_issue",
            payload={"x": 1},
            requested_by="FIN-1",
            approver_roles=["finance_head"],
            n_required=1,
            ttl_h=-1,  # already expired
        )
        expired = await store.mark_expired_if_due(created["id"])
    assert expired is not None
    assert expired["status"] == "expired"
