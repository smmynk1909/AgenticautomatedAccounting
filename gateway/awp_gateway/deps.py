"""Request-scoped dependencies — doc 11 §5. All shared clients (MCP, bus,
DB session factory) live on `app.state` (set once in `main.py`'s app
factory) and are handed out per-request through these `Depends` functions,
so tests can override them (`app.dependency_overrides`) without touching
the real Postgres/Redis/MCP servers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from awp_mcp_base.uow import UnitOfWork
from awp_shared.auth import Principal, verify_jwt
from awp_shared.bus import TaskBus
from awp_shared.errors import PermissionDeniedError
from awp_shared.mcpc import MCP
from fastapi import Depends, Header, Request


@dataclass
class GatewayState:
    mcp: MCP
    bus: TaskBus
    uow: UnitOfWork


def get_state(request: Request) -> GatewayState:
    state: GatewayState = request.app.state.gateway
    return state


def get_mcp(state: GatewayState = Depends(get_state)) -> MCP:
    return state.mcp


def get_bus(state: GatewayState = Depends(get_state)) -> TaskBus:
    return state.bus


def get_uow(state: GatewayState = Depends(get_state)) -> UnitOfWork:
    return state.uow


def get_current_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise PermissionDeniedError("missing Authorization bearer token")
    return verify_jwt(authorization[len("Bearer ") :])


def require_human(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.kind != "user":
        raise PermissionDeniedError("this endpoint requires a human session, not an agent token")
    return principal


def require_roles(*allowed: str) -> Any:
    """`Depends(require_roles("finance_head", "director"))` — 403s unless the
    caller has at least one of the listed roles. No-arg call (`require_roles()`)
    means "any authenticated human," matching `Depends(require_human)`."""

    def _check(principal: Principal = Depends(require_human)) -> Principal:
        if allowed and not set(principal.roles) & set(allowed):
            raise PermissionDeniedError(
                f"role(s) {principal.roles} not authorized (needs one of {list(allowed)})"
            )
        return principal

    return _check
