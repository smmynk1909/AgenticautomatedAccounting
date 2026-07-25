"""MCP client — doc 11 §1.5, transport per DEVIATIONS.md #6.

Attaches auth/trace/idempotency headers and maps the server's structured
error envelope (`{"error": {code, message, retryable, details}}`, doc 08 §0)
back to typed exceptions from `awp_shared.errors`. `_call_tool_raw` is the
one place that knows the wire format — see DEVIATIONS.md #6 for why it's a
plain HTTP POST instead of the real MCP JSON-RPC/SSE protocol, and swap only
this method when upgrading.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import httpx
from pydantic import BaseModel

from awp_shared.errors import AwpError, UpstreamError
from awp_shared.schemas import ErrorInfo


class McpTransportError(Exception):
    pass


class MCP:
    def __init__(
        self,
        servers: dict[str, str],
        principal_jwt_provider: Callable[[], str],
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        """`servers`: server name -> base URL, e.g. {"audit": "http://mcp-audit:8000"}."""
        self._servers = servers
        self._jwt_provider = principal_jwt_provider
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def call(
        self,
        server: str,
        tool: str,
        args: BaseModel | dict[str, Any],
        approval_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if server not in self._servers:
            raise ValueError(f"unknown MCP server: {server!r} (known: {list(self._servers)})")
        url = self._servers[server]
        payload = args.model_dump(mode="json") if isinstance(args, BaseModel) else dict(args)
        if approval_token:
            payload = {**payload, "approval_token": approval_token}

        headers = {
            "Authorization": f"Bearer {self._jwt_provider()}",
            "X-Trace-Id": str(uuid4()),
        }
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key

        try:
            result = await self._call_tool_raw(url, tool, payload, headers)
        except McpTransportError as exc:
            raise UpstreamError(f"{server}.{tool} unreachable: {exc}") from exc

        if isinstance(result, dict) and isinstance(result.get("error"), dict):
            info = ErrorInfo.model_validate(result["error"])
            raise AwpError.from_error_info(info)

        return result

    async def _call_tool_raw(
        self, url: str, tool: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        try:
            r = await self._client.post(f"{url.rstrip('/')}/tools/{tool}", json=payload, headers=headers)
        except httpx.TransportError as exc:
            raise McpTransportError(str(exc)) from exc

        try:
            data: Any = r.json()
        except json.JSONDecodeError as exc:
            raise McpTransportError(f"non-JSON response ({r.status_code}): {r.text[:200]}") from exc

        if r.status_code >= 500 and not (isinstance(data, dict) and "error" in data):
            raise McpTransportError(f"server error {r.status_code}: {data!r}")

        return data if isinstance(data, dict) else {"value": data}
