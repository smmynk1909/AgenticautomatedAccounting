"""GET/POST /api/tickets, PATCH /api/tickets/{id} — doc 11 §5, with
category ACL per `awp_gateway.rbac` (see that module's docstring).
"""

from __future__ import annotations

from typing import Any

from awp_shared.auth import Principal
from awp_shared.errors import PermissionDeniedError, ValidationError
from fastapi import APIRouter, Depends

from awp_gateway.deps import GatewayState, get_state, require_human
from awp_gateway.rbac import visible_categories

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@router.get("")
async def list_tickets(
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    allowed = visible_categories(principal)

    if category is not None:
        if allowed is not None and category not in allowed:
            raise PermissionDeniedError(
                f"role(s) {principal.roles} cannot view category {category!r}"
            )
        filters: dict[str, Any] = {"status": status, "priority": priority, "category": category}
        if allowed == frozenset():  # no department role at all -> self-service only
            filters["requester_id"] = principal.sub
        return await state.mcp.call("erp", "query_tickets", filters)

    if allowed is None:
        return await state.mcp.call(
            "erp", "query_tickets", {"status": status, "priority": priority}
        )

    if allowed == frozenset():
        return await state.mcp.call(
            "erp",
            "query_tickets",
            {"status": status, "priority": priority, "requester_id": principal.sub},
        )

    # Department role, no explicit category -> fan out across every category
    # that role can see (mcp-erp's query_tickets has no "category IN (...)").
    tickets: list[Any] = []
    for cat in allowed:
        result = await state.mcp.call(
            "erp", "query_tickets", {"status": status, "priority": priority, "category": cat}
        )
        tickets.extend(result["tickets"])
    return {"tickets": tickets}


@router.post("")
async def create_ticket(
    payload: dict[str, Any],
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    body = {
        **payload,
        "requester": {"type": "employee", "id": principal.sub},
    }
    return await state.mcp.call("erp", "create_ticket", body)


@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: str,
    payload: dict[str, Any],
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    if not payload:
        raise ValidationError("update_ticket requires a non-empty patch body")
    return await state.mcp.call(
        "erp", "update_ticket", {"ticket_id": ticket_id, "patch": payload}
    )
