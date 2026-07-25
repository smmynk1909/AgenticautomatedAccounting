"""FastAPI adapter for `AwpMcpServer` — the actual network transport, per
DEVIATIONS.md #6 (plain HTTP+JSON `POST /tools/{tool}`, not MCP/SSE).
`mcps/audit/server.py` and `mcps/approvals/server.py` call `build_asgi_app`
and hand the result to uvicorn in their `main.py`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from awp_shared.errors import AwpError

from awp_mcp_base.server import AwpMcpServer

_STATUS_BY_CODE: dict[str, int] = {
    "VALIDATION": 400,
    "NOT_FOUND": 404,
    "PERMISSION_DENIED": 403,
    "CONFLICT": 409,
    "APPROVAL_REQUIRED": 412,
    "UPSTREAM": 502,
    "INTERNAL": 500,
    "TIMEOUT": 504,
}


def build_asgi_app(server: AwpMcpServer) -> FastAPI:
    app = FastAPI(title=server.name)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"server": server.name, "tools": server.tool_names}

    @app.post("/tools/{tool_name}")
    async def call_tool(tool_name: str, request: Request) -> JSONResponse:
        body = await request.body()
        payload: dict[str, Any] = await request.json() if body else {}
        headers = dict(request.headers)
        try:
            result = await server.dispatch_raw(tool_name, payload, headers)
        except AwpError as exc:
            info = exc.to_error_info()
            return JSONResponse(
                status_code=_STATUS_BY_CODE.get(info.code, 500),
                content={"error": info.model_dump(mode="json")},
            )
        return JSONResponse(content=result if isinstance(result, dict) else {"value": result})

    return app
