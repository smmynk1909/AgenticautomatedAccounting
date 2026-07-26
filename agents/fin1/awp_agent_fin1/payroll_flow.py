"""FIN-1a PayrollRunner — doc 06 §2.1, doc 11 §6.1.

Two simplifications from the real workflow, both documented in
DEVIATIONS.md:
- Per-employee comp (basic/HRA/special) comes from `salary_bands.mid`
  (grade -> band midpoint, split 50/20/30) rather than each employee's
  real `comp_structures` row — that row is `components_encrypted`
  (`LargeBinary`) with no decrypt path built anywhere yet.
- Attendance/LOP defaults to a full month, no leave/attendance system
  exists to source real LOP days from.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from awp_agent_base.protocols import MCPLike

BASIC_PCT = Decimal("0.50")
HRA_PCT = Decimal("0.20")
SPECIAL_PCT = Decimal("0.30")

ACCOUNT_SALARIES_EXPENSE = "5001"
ACCOUNT_SALARY_PAYABLE = "2002"
ACCOUNT_PF_PAYABLE = "2003"
ACCOUNT_ESI_PAYABLE = "2004"
ACCOUNT_PT_PAYABLE = "2005"
ACCOUNT_TDS_PAYABLE = "2006"


async def gather_employees_for_payroll(
    mcp: MCPLike, employee_ids: list[str] | None
) -> list[dict[str, Any]]:
    result = await mcp.call("erp", "query_employees", {"status": "active", "page_size": 500})
    employees: list[dict[str, Any]] = result.get("employees", [])
    if employee_ids is not None:
        wanted = set(employee_ids)
        employees = [e for e in employees if e["emp_id"] in wanted]
    return employees


async def build_comp_snapshot_row(mcp: MCPLike, employee: dict[str, Any]) -> dict[str, Any]:
    bands = await mcp.call(
        "erp", "query_policies", {"domain": "salary_bands", "grade": employee["grade"]}
    )
    policies = bands.get("policies", [])
    mid = Decimal(str(policies[0]["mid"])) if policies else Decimal("600000")
    annual = mid
    monthly = annual / 12
    return {
        "emp_id": employee["emp_id"],
        "grade": employee["grade"],
        "basic": str((monthly * BASIC_PCT).quantize(Decimal("0.01"))),
        "hra": str((monthly * HRA_PCT).quantize(Decimal("0.01"))),
        "special": str((monthly * SPECIAL_PCT).quantize(Decimal("0.01"))),
        "variable": "0",
        "state": "KA",
    }


def fy_for_month(month: str) -> str:
    """"YYYY-MM" -> Indian FY string "YYYY-YY+1", e.g. "2026-06" -> "2026-27"."""
    year, mon = (int(p) for p in month.split("-"))
    fy_start = year if mon >= 4 else year - 1
    return f"{fy_start}-{str(fy_start + 1)[-2:]}"


def salary_journal_lines(totals: dict[str, str]) -> list[dict[str, Any]]:
    """Builds the aggregate salary-posting lines from a payroll register's
    `totals` (doc 06 §2.1 step 7). `gross - lop` is what's actually
    incurred as expense; `net` plus every statutory deduction must sum back
    to that same figure, or `mcp-finance.post_journal`'s own balance check
    rejects it."""
    gross = Decimal(totals.get("gross", "0"))
    lop = Decimal(totals.get("lop", "0"))
    net = Decimal(totals.get("net", "0"))
    pf = Decimal(totals.get("pf", "0"))
    esi = Decimal(totals.get("esi", "0"))
    pt = Decimal(totals.get("pt", "0"))
    tds = Decimal(totals.get("tds", "0"))
    incurred = gross - lop

    lines = [{"account": ACCOUNT_SALARIES_EXPENSE, "dr": str(incurred)}]
    if net > 0:
        lines.append({"account": ACCOUNT_SALARY_PAYABLE, "cr": str(net)})
    if pf > 0:
        lines.append({"account": ACCOUNT_PF_PAYABLE, "cr": str(pf)})
    if esi > 0:
        lines.append({"account": ACCOUNT_ESI_PAYABLE, "cr": str(esi)})
    if pt > 0:
        lines.append({"account": ACCOUNT_PT_PAYABLE, "cr": str(pt)})
    if tds > 0:
        lines.append({"account": ACCOUNT_TDS_PAYABLE, "cr": str(tds)})
    return lines
