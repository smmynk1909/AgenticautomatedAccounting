"""`make_server` — doc 11 §3 factory. Produces an `AwpMcpServer`: a tool
registry whose `.tool()` decorator mirrors FastMCP's, sitting on top of
`ToolPipeline` (auth/scope/idempotency/audit, all four "middlewares" from
the doc). `asgi.py` adapts an `AwpMcpServer` to a real HTTP service; tests
can call `dispatch_raw` directly with no network involved.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from awp_shared.audit_mw import AuditSink
from awp_shared.config import get_required_scopes
from awp_shared.errors import NotFoundError
from redis.asyncio import Redis

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.pipeline import Handler, ToolPipeline


class AwpMcpServer:
    def __init__(self, name: str, *, audit_sink: AuditSink, redis: Redis) -> None:
        self.name = name
        self._handlers: dict[str, Handler] = {}
        self._pipeline = ToolPipeline(
            server_name=name,
            get_required_scopes=get_required_scopes,
            audit_sink=audit_sink,
            redis=redis,
        )

    def tool(self, name: str | None = None) -> Callable[[Handler], Handler]:
        def decorator(fn: Handler) -> Handler:
            self._handlers[name or fn.__name__] = fn
            return fn

        return decorator

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._handlers)

    async def dispatch_raw(
        self, tool_name: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> Any:
        handler = self._handlers.get(tool_name)
        if handler is None:
            raise NotFoundError(f"unknown tool: {tool_name!r} on server {self.name!r}")
        return await self._pipeline.dispatch(tool_name, payload, headers, handler)


def make_server(name: str, *, audit_sink: AuditSink, redis: Redis) -> AwpMcpServer:
    return AwpMcpServer(name, audit_sink=audit_sink, redis=redis)


__all__ = ["AwpMcpServer", "make_server", "Ctx"]
