"""GET /api/tasks/{task_id} — doc 11 §5."""

from __future__ import annotations

from typing import Any

from awp_shared.auth import Principal
from fastapi import APIRouter, Depends

from awp_gateway.deps import GatewayState, get_state, require_human

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    return await state.mcp.call("erp", "get_task_status", {"task_id": task_id})
