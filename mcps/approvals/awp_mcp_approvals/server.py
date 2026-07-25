"""mcp-approvals' AGENT-facing tool surface — doc 08 §5. Deliberately exposes
only `request_approval` / `get_approval_status`. `approve`/`reject` live in
`service.py`, reachable only from the (Sprint-3) gateway's human-authenticated
routes — see that module's docstring for why this split is the actual
enforcement mechanism, not just a convention.
"""

from __future__ import annotations

from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer, make_server
from awp_mcp_base.uow import UnitOfWork
from awp_shared.audit_mw import AuditSink
from awp_shared.errors import NotFoundError, ValidationError
from redis.asyncio import Redis

from awp_mcp_approvals.gates import resolve_gate
from awp_mcp_approvals.store import ApprovalStore


def make_approvals_server(uow: UnitOfWork, redis: Redis, audit_sink: AuditSink) -> AwpMcpServer:
    server = make_server("approvals", audit_sink=audit_sink, redis=redis)

    @server.tool()
    async def request_approval(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        gate_name = payload.get("gate")
        approval_payload = payload.get("payload")
        if not gate_name or approval_payload is None:
            raise ValidationError("request_approval requires 'gate' and 'payload'")

        gate = resolve_gate(gate_name)
        async with uow() as session:
            record = await ApprovalStore(session).create(
                gate=gate.name,
                payload=approval_payload,
                requested_by=ctx.principal.sub,
                approver_roles=gate.approver_roles,
                n_required=gate.n_required,
                ttl_h=gate.ttl_h,
            )
        return {
            "approval_id": record["id"],
            "status": record["status"],
            "approver_roles": record["approver_roles"],
            "n_required": record["n_required"],
            "expires_at": record["expires_at"].isoformat(),
        }

    @server.tool()
    async def get_approval_status(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        approval_id = payload.get("approval_id")
        if not approval_id:
            raise ValidationError("get_approval_status requires 'approval_id'")

        async with uow() as session:
            record = await ApprovalStore(session).mark_expired_if_due(approval_id)
        if record is None:
            raise NotFoundError(f"no such approval: {approval_id}")

        result: dict[str, Any] = {
            "approval_id": approval_id,
            "status": record["status"],
            "approvals_so_far": len(record["approvals_received"]),
            "needed": record["n_required"],
        }
        if record["status"] == "approved":
            result["token"] = record["token"]
        return result

    return server
