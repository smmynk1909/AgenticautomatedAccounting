"""GET /api/dashboard/{role} — doc 03 §2.4's role-scoped Executive Action
Dashboard, doc 11 §5. Read-only: every figure already lives in
`dashboard_items` (written by `push_dashboard_item` calls from whichever
agent owns the panel) — this route never computes anything itself.
"""

from __future__ import annotations

from typing import Any

from awp_shared.auth import Principal
from awp_shared.errors import PermissionDeniedError
from fastapi import APIRouter, Depends

from awp_gateway.deps import GatewayState, get_state, require_human
from awp_gateway.rbac import can_view_dashboard_role

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/{role}")
async def get_dashboard(
    role: str,
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    if not can_view_dashboard_role(principal, role):
        raise PermissionDeniedError(f"role(s) {principal.roles} cannot view the {role!r} dashboard")
    return await state.mcp.call("erp", "get_dashboard", {"role": role})
