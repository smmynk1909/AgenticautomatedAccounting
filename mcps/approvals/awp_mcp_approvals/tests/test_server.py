import pytest
from fakeredis.aioredis import FakeRedis

from awp_shared.audit_mw import AuditEvent
from awp_shared.auth import Principal, mint_service_jwt
from awp_shared.errors import PermissionDeniedError, ValidationError

from awp_mcp_approvals.server import make_approvals_server
from awp_mcp_approvals.service import approve
from awp_mcp_approvals.store import ApprovalStore
from awp_mcp_base.uow import UnitOfWork


class _NullSink:
    async def log_event(self, event: AuditEvent) -> None:
        pass


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_request_approval_tool_creates_a_pending_record(uow: UnitOfWork) -> None:
    server = make_approvals_server(uow, FakeRedis(decode_responses=True), _NullSink())
    token = mint_service_jwt("FIN-1", ["approvals.request"])

    result = await server.dispatch_raw(
        "request_approval",
        {"gate": "invoice_issue", "payload": {"invoice_id": "INV-1"}},
        _headers(token),
    )
    assert result["status"] == "pending"
    assert result["approver_roles"] == ["finance_head"]


@pytest.mark.asyncio
async def test_request_approval_requires_scope(uow: UnitOfWork) -> None:
    server = make_approvals_server(uow, FakeRedis(decode_responses=True), _NullSink())
    token = mint_service_jwt("FIN-1", [])
    with pytest.raises(PermissionDeniedError):
        await server.dispatch_raw(
            "request_approval", {"gate": "invoice_issue", "payload": {}}, _headers(token)
        )


@pytest.mark.asyncio
async def test_request_approval_rejects_unknown_gate(uow: UnitOfWork) -> None:
    server = make_approvals_server(uow, FakeRedis(decode_responses=True), _NullSink())
    token = mint_service_jwt("FIN-1", ["approvals.request"])
    with pytest.raises(ValidationError):
        await server.dispatch_raw(
            "request_approval", {"gate": "not_a_real_gate", "payload": {}}, _headers(token)
        )


@pytest.mark.asyncio
async def test_get_approval_status_reflects_pending_then_approved(uow: UnitOfWork) -> None:
    server = make_approvals_server(uow, FakeRedis(decode_responses=True), _NullSink())
    req_token = mint_service_jwt("FIN-1", ["approvals.request"])
    read_token = mint_service_jwt("FIN-1", ["approvals.read"])

    created = await server.dispatch_raw(
        "request_approval",
        {"gate": "invoice_issue", "payload": {"invoice_id": "INV-1"}},
        _headers(req_token),
    )
    status = await server.dispatch_raw(
        "get_approval_status", {"approval_id": created["approval_id"]}, _headers(read_token)
    )
    assert status["status"] == "pending"
    assert "token" not in status

    # a human approves out-of-band (service.py, not through this agent surface)
    async with uow() as session:
        await approve(
            ApprovalStore(session),
            created["approval_id"],
            Principal(sub="dev-finance-head", kind="user", roles=["finance_head"]),
        )

    status_after = await server.dispatch_raw(
        "get_approval_status", {"approval_id": created["approval_id"]}, _headers(read_token)
    )
    assert status_after["status"] == "approved"
    assert status_after["token"]


@pytest.mark.asyncio
async def test_get_approval_status_requires_scope(uow: UnitOfWork) -> None:
    server = make_approvals_server(uow, FakeRedis(decode_responses=True), _NullSink())
    req_token = mint_service_jwt("FIN-1", ["approvals.request"])
    created = await server.dispatch_raw(
        "request_approval", {"gate": "invoice_issue", "payload": {"x": 1}}, _headers(req_token)
    )

    no_scope_token = mint_service_jwt("FIN-1", [])
    with pytest.raises(PermissionDeniedError):
        await server.dispatch_raw(
            "get_approval_status", {"approval_id": created["approval_id"]}, _headers(no_scope_token)
        )


def test_agent_facing_server_has_no_approve_or_reject_tool(uow: UnitOfWork) -> None:
    """Structural check for the doc 08 §5 guarantee: these tool names must
    never exist on the agent-facing server, for any scope."""
    server = make_approvals_server(uow, FakeRedis(decode_responses=True), _NullSink())
    assert server.tool_names == ["get_approval_status", "request_approval"]
