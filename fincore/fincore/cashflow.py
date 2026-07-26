"""fincore/cashflow.py — doc 06 §2.5's 13-week rolling cashflow.

Sourcing "committed AR/AP, payroll, rent/subscriptions, pipeline-weighted
OPS revenue" into a per-week inflow/outflow figure is a database query
concern (`mcp-finance.cashflow_model`'s job); this module only does the
deterministic part — running-balance rollup — given those figures already
computed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fincore.models import CashflowRow, round2


def cashflow_model(
    opening_balance: Decimal,
    weekly_flows: list[tuple[date, Decimal, Decimal, tuple[str, ...]]],
) -> list[CashflowRow]:
    """`weekly_flows`: `(week_start, inflow, outflow, assumptions)` tuples,
    already in chronological order."""
    rows: list[CashflowRow] = []
    balance = opening_balance
    for week_start, inflow, outflow, assumptions in weekly_flows:
        net = round2(inflow - outflow)
        balance = round2(balance + net)
        rows.append(
            CashflowRow(
                week_start=week_start,
                inflow=round2(inflow),
                outflow=round2(outflow),
                net=net,
                running_balance=balance,
                assumptions=assumptions,
            )
        )
    return rows


def first_negative_week(rows: list[CashflowRow]) -> date | None:
    """The runway/funding-gap signal doc 06 §2.5 asks for: the first week
    the running balance would go negative, or `None` if it never does
    across the modeled horizon."""
    for row in rows:
        if row.running_balance < 0:
            return row.week_start
    return None
