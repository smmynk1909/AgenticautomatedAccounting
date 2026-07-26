"""FIN-1e FPnA — doc 06 §2.5.

The real 13-week model sources "committed AR/AP, payroll, rent/
subscriptions from recurring table, pipeline-weighted from OPS" — none of
that aggregation exists yet (recurring-expense lookups, AR/AP aging, and
OPS-1's pipeline are all later/unbuilt). This build projects a flat weekly
outflow from the trailing month's actual expense run-rate (`get_pnl`) and
zero projected inflow (the conservative direction — never overstates
runway) off the current bank balance, clearly short of doc 06's full model
but still real numbers from the ledger, not fabricated ones (doc 06 §4
rule 1).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from awp_agent_base.protocols import MCPLike

WEEKS_PER_MONTH = Decimal("4.33")


async def project_weekly_flows(
    mcp: MCPLike, period: str, horizon_weeks: int, start: date
) -> tuple[Decimal, list[tuple[date, Decimal, Decimal, tuple[str, ...]]]]:
    pnl_result = await mcp.call("finance", "get_pnl", {"period": period})
    monthly_expense = Decimal(pnl_result.get("expense", "0"))
    weekly_outflow = (monthly_expense / WEEKS_PER_MONTH).quantize(Decimal("0.01"))

    balance_sheet = await mcp.call(
        "finance", "get_balance_sheet", {"date": start.isoformat()}
    )
    opening_balance = Decimal(balance_sheet.get("asset", "0"))

    assumption: tuple[str, ...] = (
        f"flat weekly outflow projected from {period}'s actual expense run-rate",
    )
    flows = [
        (start + timedelta(weeks=i), Decimal("0"), weekly_outflow, assumption)
        for i in range(horizon_weeks)
    ]
    return opening_balance, flows
