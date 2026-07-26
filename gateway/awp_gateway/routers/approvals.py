"""GET /api/approvals/inbox, POST /api/approvals/{id}/approve|reject — doc
11 §5. Per `awp_mcp_approvals/service.py`'s docstring, this calls straight
into that module's `approve`/`reject` (never an MCP tool call — doc 08 §5:
"no agent scope can ever approve," enforced by there being no such tool),
using the gateway's own DB session against the same `approvals` table.
"""

from __future__ import annotations

from typing import Any

from awp_mcp_approvals.service import approve as do_approve
from awp_mcp_approvals.service import reject as do_reject
from awp_mcp_approvals.store import ApprovalStore
from awp_shared.auth import Principal
from awp_shared.errors import ValidationError
from fastapi import APIRouter, Depends

from awp_gateway.deps import GatewayState, get_state, require_human

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("/inbox")
async def inbox(
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    async with state.uow() as session:
        pending = await ApprovalStore(session).list_pending(roles=principal.roles)
    return {"approvals": pending}


@router.post("/{approval_id}/approve")
async def approve_endpoint(
    approval_id: str,
    payload: dict[str, Any],
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    async with state.uow() as session:
        return await do_approve(
            ApprovalStore(session), approval_id, principal, payload.get("comment", "")
        )


@router.post("/{approval_id}/reject")
async def reject_endpoint(
    approval_id: str,
    payload: dict[str, Any],
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    reason = payload.get("reason")
    if not reason:
        raise ValidationError("reject requires 'reason'")
    async with state.uow() as session:
        return await do_reject(ApprovalStore(session), approval_id, principal, reason)
