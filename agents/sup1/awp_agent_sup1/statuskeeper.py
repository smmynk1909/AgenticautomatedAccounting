"""SUP-1c StatusKeeper — doc 07 §3.3: any `ticket_event` -> `summary_current`
regenerated, "must mention latest event + next step + who holds the ball."
"""

from __future__ import annotations

import json
from typing import Any

from awp_agent_base.protocols import LLMLike, MCPLike


async def refresh_summary(llm: LLMLike, mcp: MCPLike, ticket_id: str) -> str:
    ticket = await mcp.call("erp", "get_ticket", {"ticket_id": ticket_id})
    events: list[dict[str, Any]] = ticket.get("events", [])
    latest = events[-1] if events else None

    messages = [
        {
            "role": "system",
            "content": (
                "Summarize this ticket's status in at most 120 words. You MUST "
                "mention the latest event, the next step, and who currently "
                "holds the ball."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "ticket_id": ticket_id,
                    "status": ticket.get("status"),
                    "assignee": ticket.get("assignee_id"),
                    "latest_event": latest,
                },
                default=str,
            ),
        },
    ]
    resp = await llm.chat(messages, profile="draft")
    summary = resp.content or ""
    await mcp.call("erp", "set_summary", {"ticket_id": ticket_id, "text": summary})
    return summary
