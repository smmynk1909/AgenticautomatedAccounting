"""GET /api/payroll/runs/{month} — doc 11 §5. Read-only: proxies
`mcp-finance.get_payroll_run` (Sprint 6 addition — see that tool's
docstring for why it exists) behind a payroll-specific RBAC check, since a
payroll register carries every employee's compensation.
"""

from __future__ import annotations

from typing import Any

from awp_shared.auth import Principal
from awp_shared.errors import PermissionDeniedError
from fastapi import APIRouter, Depends

from awp_gateway.deps import GatewayState, get_state, require_human
from awp_gateway.rbac import can_view_payroll

router = APIRouter(prefix="/api/payroll", tags=["payroll"])


@router.get("/runs/{month}")
async def get_payroll_run(
    month: str,
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    if not can_view_payroll(principal):
        raise PermissionDeniedError(f"role(s) {principal.roles} cannot view payroll data")
    return await state.mcp.call("finance", "get_payroll_run", {"month": month})
