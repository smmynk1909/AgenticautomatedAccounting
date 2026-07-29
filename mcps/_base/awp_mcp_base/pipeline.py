"""Transport-agnostic tool-call pipeline — doc 11 §3's four middlewares
(`auth_mw`, `scope_mw`, `audit_mw`, `idempotency_mw`) as one composable,
directly unit-testable object instead of guessed FastMCP hook signatures
(see DEVIATIONS.md #6). `server.py` wraps this for the HTTP adapter.

Order: authenticate -> authorize (scope check) -> idempotency replay check ->
call handler, audited -> cache result if idempotent. Approval-token
verification is NOT here — doc 11 §3's example shows each 🔒 tool checking
its own gate inline (`if needs_gate(args): verify_approval_token(...)`),
since only the tool knows its own condition (e.g. `expense_posting` only
above a threshold). `Ctx.approval_token` carries the token through for the
handler to use.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from awp_shared.audit_mw import AuditMiddleware, AuditSink
from awp_shared.auth import Principal, require_scopes, verify_jwt
from awp_shared.errors import AwpError, ValidationError
from awp_shared.metrics import mcp_tool_call_duration_seconds, mcp_tool_calls_total
from awp_shared.tracing import start_span
from redis.asyncio import Redis

from awp_mcp_base.ctx import Ctx

IDEMPOTENCY_TTL_S = 7 * 24 * 3600

ScopeLookup = Callable[[str, str], list[str]]
Handler = Callable[[dict[str, Any], Ctx], Awaitable[Any]]


def _to_jsonable(result: Any) -> Any:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result


def _get_header(headers: dict[str, str], name: str) -> str | None:
    # ASGI (ergo real HTTP transport) lowercases every header name; in-process
    # tests build headers dicts with "natural" casing. Look up case-insensitively
    # so both work identically.
    target = name.lower()
    for k, v in headers.items():
        if k.lower() == target:
            return v
    return None


class ToolPipeline:
    def __init__(
        self,
        *,
        server_name: str,
        get_required_scopes: ScopeLookup,
        audit_sink: AuditSink,
        redis: Redis,
    ) -> None:
        self._server_name = server_name
        self._get_required_scopes = get_required_scopes
        self._audit_sink = audit_sink
        self._redis = redis

    async def dispatch(
        self,
        tool_name: str,
        raw_payload: dict[str, Any],
        headers: dict[str, str],
        handler: Handler,
    ) -> Any:
        principal = self._authenticate(headers)
        self._authorize(principal, tool_name)

        idem_key = _get_header(headers, "X-Idempotency-Key")
        cache_key = f"idem:{self._server_name}:{tool_name}:{idem_key}" if idem_key else None
        if cache_key:
            cached = await self._redis.get(cache_key)
            if cached is not None:
                return json.loads(cached)

        payload = dict(raw_payload)
        approval_token = payload.pop("approval_token", None)
        ctx = Ctx(
            principal=principal,
            trace_id=_get_header(headers, "X-Trace-Id") or "",
            idempotency_key=idem_key,
            approval_token=approval_token,
        )

        mw = AuditMiddleware(
            self._audit_sink, agent_id=principal.sub, server_name=self._server_name
        )

        async def call_fn() -> Any:
            return await handler(payload, ctx)

        start = time.monotonic()
        status = "ok"
        try:
            with start_span(
                f"mcp.{self._server_name}.{tool_name}",
                trace_id=ctx.trace_id or None,
                server=self._server_name,
                tool=tool_name,
            ):
                result = await mw.wrap(tool_name, raw_payload, call_fn)
        except AwpError as exc:
            status = exc.code
            raise
        except Exception:
            status = "internal_error"
            raise
        finally:
            duration = time.monotonic() - start
            mcp_tool_calls_total.labels(self._server_name, tool_name, status).inc()
            mcp_tool_call_duration_seconds.labels(self._server_name, tool_name).observe(duration)

        if cache_key:
            await self._redis.set(cache_key, json.dumps(_to_jsonable(result)), ex=IDEMPOTENCY_TTL_S)

        return result

    def _authenticate(self, headers: dict[str, str]) -> Principal:
        auth_header = _get_header(headers, "Authorization") or ""
        if not auth_header.startswith("Bearer "):
            raise ValidationError("missing Authorization bearer token")
        return verify_jwt(auth_header[len("Bearer ") :])

    def _authorize(self, principal: Principal, tool_name: str) -> None:
        needed = self._get_required_scopes(self._server_name, tool_name)
        require_scopes(principal, needed)
