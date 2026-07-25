import pytest
from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import Principal, mint_service_jwt, verify_approval_token, verify_jwt
from awp_shared.errors import (
    ApprovalRequiredError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from fakeredis.aioredis import FakeRedis

from awp_mcp_approvals.service import approve, reject
from awp_mcp_approvals.store import ApprovalStore

FINANCE_HEAD = Principal(sub="dev-finance-head", kind="user", roles=["finance_head", "finance"])
DIRECTOR = Principal(sub="dev-director", kind="user", roles=["director"])
RECRUITER = Principal(sub="dev-recruiter", kind="user", roles=["recruiter"])


async def _create(uow: UnitOfWork, *, gate: str, approver_roles: list[str], n_required: int) -> str:
    async with uow() as session:
        record = await ApprovalStore(session).create(
            gate=gate,
            payload={"amount": 100000},
            requested_by="FIN-1",
            approver_roles=approver_roles,
            n_required=n_required,
            ttl_h=24,
        )
    return record["id"]  # type: ignore[no-any-return]


@pytest.mark.asyncio
async def test_single_approver_gate_mints_token_immediately(uow: UnitOfWork) -> None:
    approval_id = await _create(
        uow, gate="invoice_issue", approver_roles=["finance_head"], n_required=1
    )
    async with uow() as session:
        result = await approve(ApprovalStore(session), approval_id, FINANCE_HEAD)

    assert result["status"] == "approved"
    assert "token" in result

    redis = FakeRedis(decode_responses=True)
    verified = await verify_approval_token(
        result["token"], "invoice_issue", {"amount": 100000}, redis=redis
    )
    assert verified.approvers == ["dev-finance-head"]


@pytest.mark.asyncio
async def test_maker_checker_gate_requires_both_approvers(uow: UnitOfWork) -> None:
    approval_id = await _create(
        uow, gate="payroll_run", approver_roles=["finance_head", "director"], n_required=2
    )

    async with uow() as session:
        first = await approve(ApprovalStore(session), approval_id, FINANCE_HEAD)
    assert first["status"] == "pending"
    assert first["approvals_so_far"] == 1
    assert "token" not in first

    async with uow() as session:
        second = await approve(ApprovalStore(session), approval_id, DIRECTOR)
    assert second["status"] == "approved"
    assert "token" in second


@pytest.mark.asyncio
async def test_no_agent_scope_can_ever_approve(uow: UnitOfWork) -> None:
    """The core doc 08 §5 guarantee: even a maximally-scoped agent JWT is
    rejected purely on `kind`, before any role check happens."""
    approval_id = await _create(
        uow, gate="invoice_issue", approver_roles=["finance_head"], n_required=1
    )
    forged_agent_token = mint_service_jwt(
        "FIN-1", ["approvals.request", "approvals.read", "finance.write"]
    )
    agent_principal = verify_jwt(forged_agent_token)
    assert agent_principal.kind == "agent"

    async with uow() as session:
        with pytest.raises(PermissionDeniedError, match="human"):
            await approve(ApprovalStore(session), approval_id, agent_principal)


@pytest.mark.asyncio
async def test_wrong_role_cannot_approve(uow: UnitOfWork) -> None:
    approval_id = await _create(
        uow, gate="invoice_issue", approver_roles=["finance_head"], n_required=1
    )
    async with uow() as session:
        with pytest.raises(PermissionDeniedError, match="not authorized"):
            await approve(ApprovalStore(session), approval_id, RECRUITER)


@pytest.mark.asyncio
async def test_same_approver_cannot_vote_twice_maker_checker(uow: UnitOfWork) -> None:
    approval_id = await _create(
        uow, gate="payroll_run", approver_roles=["finance_head", "director"], n_required=2
    )
    async with uow() as session:
        await approve(ApprovalStore(session), approval_id, FINANCE_HEAD)
    async with uow() as session:
        with pytest.raises(ConflictError, match="already voted"):
            await approve(ApprovalStore(session), approval_id, FINANCE_HEAD)


@pytest.mark.asyncio
async def test_reject_then_approve_is_rejected_as_conflict(uow: UnitOfWork) -> None:
    approval_id = await _create(
        uow, gate="invoice_issue", approver_roles=["finance_head"], n_required=1
    )
    async with uow() as session:
        await reject(ApprovalStore(session), approval_id, FINANCE_HEAD, "budget not confirmed")
    async with uow() as session:
        with pytest.raises(ConflictError, match="not pending"):
            await approve(ApprovalStore(session), approval_id, FINANCE_HEAD)


@pytest.mark.asyncio
async def test_expired_approval_cannot_be_approved(uow: UnitOfWork) -> None:
    async with uow() as session:
        record = await ApprovalStore(session).create(
            gate="invoice_issue",
            payload={"amount": 1},
            requested_by="FIN-1",
            approver_roles=["finance_head"],
            n_required=1,
            ttl_h=-1,
        )
    async with uow() as session:
        with pytest.raises(ConflictError, match="not pending"):
            await approve(ApprovalStore(session), record["id"], FINANCE_HEAD)


@pytest.mark.asyncio
async def test_approving_unknown_id_raises_not_found(uow: UnitOfWork) -> None:
    async with uow() as session:
        with pytest.raises(NotFoundError):
            await approve(ApprovalStore(session), "does-not-exist", FINANCE_HEAD)


@pytest.mark.asyncio
async def test_minted_token_rejects_tampered_payload_end_to_end(uow: UnitOfWork) -> None:
    approval_id = await _create(
        uow, gate="invoice_issue", approver_roles=["finance_head"], n_required=1
    )
    async with uow() as session:
        result = await approve(ApprovalStore(session), approval_id, FINANCE_HEAD)

    redis = FakeRedis(decode_responses=True)
    with pytest.raises(ApprovalRequiredError, match="payload hash mismatch"):
        await verify_approval_token(
            result["token"], "invoice_issue", {"amount": 999999}, redis=redis
        )
