"""Daily audit-chain tamper check — doc 09 §3 "audit chain verifies daily",
doc 12 §6 exit checklist. `mcp-audit.export_audit` already recomputes each
day's Merkle root and compares it to what was stored at day-close
(`awp_mcp_audit/verifier.py`) — this just calls that once a day for
yesterday and escalates if it ever finds a mismatch. Same "scheduler makes
a direct MCP call, no agent graph needed for pure deterministic checks"
shape as `dispatcher.reconcile_sweep`, not a new pattern.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import structlog
from awp_agent_base.protocols import MCPLike

logger = structlog.get_logger(__name__)


async def verify_audit_chain_daily(mcp: MCPLike, today: date) -> dict[str, Any]:
    day = (today - timedelta(days=1)).isoformat()
    result = await mcp.call("audit", "export_audit", {"start_day": day, "end_day": day})
    reports: list[dict[str, Any]] = result.get("days", [])
    tampered = [r for r in reports if r.get("tampered")]

    if not tampered:
        logger.info(
            "audit.chain_verified",
            day=day,
            event_count=sum(r.get("event_count", 0) for r in reports),
        )
        return {"day": day, "tampered": False, "reports": reports}

    # A tampered audit day is a security incident, not a data-quality one —
    # escalate the same way HR-1/OPS-1's S1 paths do (notify_user +
    # push_dashboard_item), never just log-and-continue.
    logger.error("audit.chain_tampered", days=[r["day"] for r in tampered])
    for r in tampered:
        await mcp.call(
            "comms",
            "notify_user",
            {
                "user_id": "director",
                "subject": "AUDIT CHAIN TAMPER DETECTED",
                "body": (
                    f"Merkle root mismatch for {r['day']}: "
                    f"stored={r['stored_root']} recomputed={r['recomputed_root']}. "
                    "Investigate immediately — see deploy/runbooks/incident.md."
                ),
                "refs": {"day": r["day"]},
            },
        )
    await mcp.call(
        "erp",
        "push_dashboard_item",
        {
            "item": {
                "audience_roles": ["director", "admin_head"],
                "panel": "audit_integrity",
                "severity": "critical",
                "title": f"Audit chain tamper detected: {', '.join(r['day'] for r in tampered)}",
                "body": "Merkle root mismatch — see notify_user detail / logs.",
                "action_link": None,
                "source_task_id": None,
            }
        },
    )
    return {"day": day, "tampered": True, "reports": reports}
