"""Cashflow tool — doc 06 §2.5, doc 08 §2. `weekly_flows` is caller-supplied
(sourcing committed AR/AP, payroll, recurring expenses, and OPS pipeline
weighting is a cross-service aggregation job for FIN-1/FPnA, not something
mcp-finance can reach on its own) — see `fincore/cashflow.py`'s docstring.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.server import AwpMcpServer
from awp_shared.errors import ValidationError
from fincore.cashflow import cashflow_model as fincore_cashflow_model
from fincore.cashflow import first_negative_week

from awp_mcp_finance.wire import parse_date


def register_cashflow_tools(server: AwpMcpServer) -> None:
    @server.tool()
    async def cashflow_model(payload: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        opening_balance = payload.get("opening_balance")
        weekly_flows = payload.get("weekly_flows")
        if opening_balance is None or not weekly_flows:
            raise ValidationError("cashflow_model requires 'opening_balance' and 'weekly_flows'")

        parsed_flows: list[tuple[date, Decimal, Decimal, tuple[str, ...]]] = []
        for row in weekly_flows:
            week_start = parse_date(row["week_start"])
            if week_start is None:
                raise ValidationError("cashflow_model: 'week_start' is required on every row")
            parsed_flows.append(
                (
                    week_start,
                    Decimal(str(row["inflow"])),
                    Decimal(str(row["outflow"])),
                    tuple(row.get("assumptions", [])),
                )
            )
        rows = fincore_cashflow_model(Decimal(str(opening_balance)), parsed_flows)
        gap_week = first_negative_week(rows)

        return {
            "rows": [
                {
                    "week_start": r.week_start.isoformat(),
                    "inflow": str(r.inflow),
                    "outflow": str(r.outflow),
                    "net": str(r.net),
                    "running_balance": str(r.running_balance),
                    "assumptions": list(r.assumptions),
                }
                for r in rows
            ],
            "first_negative_week": gap_week.isoformat() if gap_week else None,
        }
