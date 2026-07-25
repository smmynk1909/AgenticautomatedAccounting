"""Dashboard tools — doc 08 §1 "Dashboard", doc 03 §2.4.

`push_dashboard_item`'s validated shape matches doc 03 §2.4's row exactly
(`source_task_id`, not doc 08 §1's shorthand `source`). All figures in a
dashboard item must already be final by the time they reach here — doc 03
§4 rule 1: DashboardComposer's LLM job is summarization/prioritization only,
never generating the numbers themselves; this tool doesn't compute anything,
only stores what it's given.
"""

from __future__ import annotations

import uuid
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_mcp_base.uow import UnitOfWork
from awp_shared.errors import ValidationError

from awp_mcp_erp.repos.dashboard import DashboardItemRepo
from awp_mcp_erp.wire import parse_datetime

REQUIRED_FIELDS = ("audience_roles", "panel", "title", "body")


def register_dashboard_tools(server: AwpMcpServer, uow: UnitOfWork) -> None:
    @server.tool()
    async def push_dashboard_item(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        item = payload.get("item", payload)
        missing = [f for f in REQUIRED_FIELDS if not item.get(f)]
        if missing:
            raise ValidationError(f"push_dashboard_item missing fields: {missing}")
        if len(item["body"]) > 400:
            raise ValidationError("push_dashboard_item body must be <= 400 characters")

        item_id = str(uuid.uuid4())
        async with uow() as session:
            await DashboardItemRepo(session).insert(
                {
                    "id": item_id,
                    "audience_roles": item["audience_roles"],
                    "panel": item["panel"],
                    "severity": item.get("severity", "info"),
                    "title": item["title"],
                    "body": item["body"],
                    "action_link": item.get("action_link"),
                    "expires_at": parse_datetime(item.get("expires_at")),
                    "source_task_id": item.get("source_task_id"),
                }
            )
        return {"id": item_id}

    @server.tool()
    async def get_dashboard(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        role = payload.get("role")
        if not role:
            raise ValidationError("get_dashboard requires 'role'")
        async with uow() as session:
            items = await DashboardItemRepo(session).active_for_role(role)
        return {"items": items}
