"""Gateway app factory — doc 11 §5. Split from `main.py` so tests can build
the FastAPI app around a fake `GatewayState` without needing real Postgres/
Redis/MCP servers (same reason `mcps/*/main.py` module-level construction is
never imported by that server's own tests).
"""

from __future__ import annotations

from awp_shared.errors import AwpError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from awp_gateway.deps import GatewayState
from awp_gateway.routers import (
    approvals,
    chat,
    codeassist,
    dashboard,
    dev_auth,
    oidc_auth,
    payroll,
    tasks,
    tickets,
)
from awp_gateway.ws import router as ws_router

_STATUS_MAP = {
    "VALIDATION": 400,
    "NOT_FOUND": 404,
    "PERMISSION_DENIED": 403,
    "CONFLICT": 409,
    "APPROVAL_REQUIRED": 412,
    "UPSTREAM": 502,
    "INTERNAL": 500,
    "TIMEOUT": 504,
}


def create_app(state: GatewayState) -> FastAPI:
    app = FastAPI(title="AWP Gateway")
    app.state.gateway = state

    @app.exception_handler(AwpError)
    async def _awp_error_handler(request: Request, exc: AwpError) -> JSONResponse:
        return JSONResponse(
            status_code=_STATUS_MAP.get(exc.code, 500),
            content={"error": exc.to_error_info().model_dump(mode="json")},
        )

    app.include_router(dev_auth.router)
    app.include_router(oidc_auth.router)
    app.include_router(chat.router)
    app.include_router(tasks.router)
    app.include_router(tickets.router)
    app.include_router(dashboard.router)
    app.include_router(payroll.router)
    app.include_router(approvals.router)
    app.include_router(codeassist.router)
    app.include_router(ws_router)
    return app
