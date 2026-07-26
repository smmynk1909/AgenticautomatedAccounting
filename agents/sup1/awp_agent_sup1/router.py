"""SUP-1b Router — doc 07 §3.2. Routing matrix is config
(`config/routing.yaml`), not prompt.
"""

from __future__ import annotations

from typing import Any

from awp_agent_base.protocols import MCPLike
from awp_shared.config import load_config


def resolve_owner(category: str) -> str:
    routing: dict[str, Any] = load_config("routing")
    entry = routing.get(category) or routing.get("unknown", {"owner": "human:support_lead"})
    owner: str = entry["owner"]
    return owner


async def fan_out_cross_functional(
    mcp: MCPLike, parent_ticket_id: str, departments: list[str], requester: dict[str, str]
) -> list[str]:
    """doc 07 §3.2: "one parent + child tickets per department, each with
    own SLA; parent auto-updates from children; parent resolves only when
    all children resolve" — that invariant is enforced by
    `mcp-erp.update_ticket` (doc 07 §6 acceptance test 2), not here; this
    just creates and links the children.
    """
    child_ids: list[str] = []
    for dept_category in departments:
        result = await mcp.call(
            "erp",
            "create_ticket",
            {
                "channel": "agent",
                "requester": requester,
                "category": dept_category,
                "subject": f"Cross-functional request (parent {parent_ticket_id})",
                "body": f"Child ticket for parent {parent_ticket_id}",
                "parent_ticket_id": parent_ticket_id,
            },
        )
        child_ids.append(result["ticket_id"])
    await mcp.call("erp", "link_tickets", {"parent": parent_ticket_id, "children": child_ids})
    return child_ids
