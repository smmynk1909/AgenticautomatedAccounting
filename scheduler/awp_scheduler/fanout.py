"""Fan-out resolvers referenced by `jobs.yaml`'s `fan_out` — doc 02 §7,
Sprint 9. Each returns one `TaskEnvelope` payload per item to dispatch;
`dispatcher.dispatch_due_jobs` fires one envelope per returned payload.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from awp_agent_base.protocols import MCPLike


async def active_projects(now: datetime, mcp: MCPLike) -> list[dict[str, Any]]:
    result = await mcp.call("erp", "query_projects", {"status": "active", "page_size": 200})
    return [{"project_id": p["id"]} for p in result.get("projects", [])]


FAN_OUT_FNS: dict[str, Callable[[datetime, MCPLike], Awaitable[list[dict[str, Any]]]]] = {
    "active_projects": active_projects,
}
