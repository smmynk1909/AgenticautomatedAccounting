"""Anomaly pass — doc 06 §2.1 step 3: "net-pay delta vs last month > +-15%
-> flagged with computed reason... unexplained -> human review list."

A real delta-vs-last-month comparison needs a way to read back a prior
month's computed register; `mcp-finance` doesn't expose one (doc 08 §2's
tool list has no `get_payroll_run`) — deferred pending that. This build
does the sanity-check half instead: unusual composition *within* the
current register (TDS eating an implausible share of gross, or net pay at
or below zero) still catches the class of error doc 06 cares about
(a badly wrong tax-table version, a data-entry mistake), just not via
month-over-month trend.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

TDS_SHARE_FLAG_THRESHOLD = Decimal("0.50")


def flag_anomalies(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for line in lines:
        gross = Decimal(line["gross"])
        net = Decimal(line["net"])
        tds = Decimal(line["deductions"].get("tds", "0"))
        if net <= 0:
            flags.append({"emp_id": line["emp_id"], "reason": "net pay is zero or negative"})
        elif gross > 0 and tds / gross > TDS_SHARE_FLAG_THRESHOLD:
            flags.append({"emp_id": line["emp_id"], "reason": "TDS exceeds 50% of gross pay"})
    return flags
