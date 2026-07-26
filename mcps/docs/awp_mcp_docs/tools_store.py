"""Storage tools — doc 08 §3: `store_file(bytes|uri, scope, retention) ->
MinIO URI`, `get_file(uri)` (scope-checked). Bytes travel over the wire
base64-encoded (JSON has no binary type — DEVIATIONS.md #6's plain
HTTP+JSON transport).
"""

from __future__ import annotations

import base64
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_shared.errors import NotFoundError, PermissionDeniedError, ValidationError

from awp_mcp_docs.storage import DocStorage


def _scope_allows(scope: list[str] | str, principal_roles: list[str]) -> bool:
    if scope == "public":
        return True
    if isinstance(scope, str):
        scope = [scope]
    return bool(set(scope) & set(principal_roles))


def register_store_tools(server: AwpMcpServer, storage: DocStorage) -> None:
    @server.tool()
    async def store_file(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        content_b64 = payload.get("content_base64")
        filename = payload.get("filename")
        if not content_b64 or not filename:
            raise ValidationError("store_file requires 'content_base64' and 'filename'")
        try:
            # binascii.Error (b64decode's actual raise on bad padding/chars)
            # is a ValueError subclass — catching ValueError covers both.
            data = base64.b64decode(content_b64, validate=True)
        except ValueError as exc:
            raise ValidationError(f"content_base64 is not valid base64: {exc}") from exc

        uri = storage.put(
            data,
            filename=filename,
            content_type=payload.get("content_type", "application/octet-stream"),
            scope=payload.get("scope", "public"),
        )
        return {"uri": uri}

    @server.tool()
    async def get_file(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        uri = payload.get("uri")
        if not uri:
            raise ValidationError("get_file requires 'uri'")
        try:
            stored = storage.get(uri)
        except FileNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc

        if not _scope_allows(stored.scope, ctx.principal.roles):
            raise PermissionDeniedError(f"principal not in scope {stored.scope!r} for {uri}")

        return {
            "content_base64": base64.b64encode(stored.data).decode("ascii"),
            "filename": stored.filename,
            "content_type": stored.content_type,
        }
