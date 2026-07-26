"""SUP-1e Reporter — doc 07 §3.5. This build implements only the daily
SQL-aggregate panels ("open by category/priority/agent, breaches, aging
outliers"). The weekly Top-Issues report's embed -> HDBSCAN -> LLM-named
clusters step and KB-gap mining are deferred — doc 07 §6 acceptance test 5
("human raters >= 4/5 usefulness on 4 consecutive weeks before Reporter
runs unattended") structurally can't be satisfied in one build pass anyway,
and no `mcp-search` (Sprint 7) exists yet to embed/cluster against.
"""

from __future__ import annotations

from collections import Counter

from awp_agent_base.protocols import MCPLike

# `query_tickets` matches one exact status per call (doc 08 §1 tool
# contract) — "open" isn't a single status, so this sums across every
# non-terminal one instead of a single aggregate query.
_OPEN_STATUSES = ("new", "triaged", "assigned", "in_progress", "waiting_requester")


async def open_ticket_counts_by_category_priority(mcp: MCPLike) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for status in _OPEN_STATUSES:
        result = await mcp.call("erp", "query_tickets", {"status": status, "limit": 1000})
        for t in result.get("tickets", []):
            counts[f"{t['category']}:{t['priority']}"] += 1
    return dict(counts)


async def push_daily_dashboard(mcp: MCPLike) -> dict[str, int]:
    counts = await open_ticket_counts_by_category_priority(mcp)
    body = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no open tickets"
    await mcp.call(
        "erp",
        "push_dashboard_item",
        {
            "audience_roles": ["support_lead", "director"],
            "panel": "ticket_fabric",
            "severity": "info",
            "title": "Open tickets by category/priority",
            "body": body[:400],
        },
    )
    return counts
