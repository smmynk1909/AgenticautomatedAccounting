"""Payroll-run repository — doc 09 §1 `payroll_runs`. One row per month,
`register` holds both the frozen snapshot (until `compute_payroll` runs)
and the computed register (after) — see `tools_payroll.py`'s docstring for
why one row covers both states.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_finance.tables import payroll_runs


class PayrollRunRepo(RepoBase):
    table = payroll_runs

    async def get_by_month(self, month: str) -> dict[str, Any] | None:
        row = (
            (await self.session.execute(select(payroll_runs).where(payroll_runs.c.month == month)))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def tds_deducted_so_far_by_emp(self, fy: str, before_month: str) -> dict[str, Decimal]:
        """Sums each employee's `tds` deduction across every already-computed
        run in FY `fy` (Indian FY: April `fy[:4]` through March of the
        following year) strictly before `before_month` — what `compute_line`
        needs as `tds_deducted_so_far` to correctly spread the remaining
        annual liability over the remaining months (doc 06 §2.1 step 2).
        Reads `register["computed"]["lines"]` — a not-yet-computed run's
        `register` has no `"computed"` key at all, so it's silently skipped
        rather than treated as zero-lines-with-zero-tds (same result, but
        `.get("computed") or {}` makes that explicit instead of accidental)."""
        fy_start_month = f"{fy[:4]}-04"
        rows = (await self.session.execute(select(payroll_runs))).mappings().all()
        totals: dict[str, Decimal] = {}
        for row in rows:
            month = row["month"]
            if not (fy_start_month <= month < before_month):
                continue
            register = row.get("register") or {}
            computed = register.get("computed") or {}
            for line in computed.get("lines", []):
                tds = Decimal(str(line.get("deductions", {}).get("tds", "0")))
                emp_id = line["emp_id"]
                totals[emp_id] = totals.get(emp_id, Decimal("0")) + tds
        return totals
