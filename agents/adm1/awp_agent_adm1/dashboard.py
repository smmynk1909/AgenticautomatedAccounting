"""ADM-1d DashboardComposer — doc 03 §2.4.

This build covers ADM-1's own asset-register panel (director/CEO audience).
The full cross-department Executive Action Dashboard (payroll-due flags from
FIN-1, delivery risk from OPS-1, headcount vs plan, hiring funnel, pending
device-acknowledgment panel) needs those agents' own `push_dashboard_item`
calls and an assignment-level query tool this build doesn't have (no
`query_asset_assignments` MCP tool exists — `mcp-erp` only exposes
`get_asset`'s per-asset history, not a cross-asset "issued, not yet
acknowledged" filter) — deferred, same scoping SUP-1's Reporter used for its
own weekly-report step.

doc 03 §4 rule 1 / doc 03 §2.4: "DashboardComposer's LLM job is
summarization and prioritization only ... all numbers come from SQL views,
never generated." This build has exactly one panel and no cross-item
prioritization decision to make yet, so there's no LLM call here at all —
the body is built from `asset_audit_report`'s own numbers, verbatim (same
choice SUP-1's `reporter.push_daily_dashboard` made). A future sprint adding
more ADM-1 panels is where the summarize/rank LLM step actually earns its
keep.
"""

from __future__ import annotations

from typing import Any

from awp_agent_base.protocols import MCPLike


async def push_asset_register_panel(mcp: MCPLike) -> dict[str, Any]:
    report = await mcp.call("erp", "asset_audit_report", {})
    by_status = ", ".join(f"{k}={v}" for k, v in sorted(report.get("by_status", {}).items()))
    body = f"{report['count']} assets, total value {report['total_value']}" + (
        f" ({by_status})" if by_status else ""
    )
    await mcp.call(
        "erp",
        "push_dashboard_item",
        {
            "audience_roles": ["director", "ceo"],
            "panel": "asset_register",
            "severity": "info",
            "title": "Asset register summary",
            "body": body[:400],
        },
    )
    return report
