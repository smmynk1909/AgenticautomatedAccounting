"""fincore/payroll.py — doc 06 §2.1 step 2, doc 11 §4.

`compute_line`'s TDS figure needs FY-to-date state (`tds_deducted_so_far`,
`months_remaining`) that a single monthly run has no memory of by itself —
fincore stays pure by taking that as an explicit input instead of tracking
it internally; `mcp-finance`'s tool handler is the one place with access to
prior `payroll_runs` rows to compute it from.
"""

from __future__ import annotations

from decimal import Decimal

from fincore.models import (
    AnnualIncome,
    Attendance,
    Declarations,
    EmpComp,
    PayrollLine,
    PayrollRegister,
    PayrollSnapshot,
    TaxTables,
    round2,
)
from fincore.tax import project_tds


def compute_line(
    emp: EmpComp,
    att: Attendance,
    t: TaxTables,
    *,
    fy: str,
    regime: str = "new",
    declarations: Declarations | None = None,
    months_elapsed: int = 0,
    tds_deducted_so_far: Decimal = Decimal("0"),
) -> PayrollLine:
    gross = round2(emp.basic + emp.hra + emp.special + emp.variable)

    lop = round2(gross / att.days_in_month * att.lop_days) if att.lop_days else Decimal("0")

    pf = Decimal("0")
    if emp.pf_opt_in:
        pf = round2(min(emp.basic, t.pf_wage_ceiling) * t.pf_employee_rate)

    esi = Decimal("0")
    if gross <= t.esi_gross_threshold:
        esi = round2(gross * t.esi_employee_rate)

    pt = Decimal("0")
    for slab in t.pt_states.get(emp.state, ()):
        if gross >= slab.income_from and (slab.income_to is None or gross < slab.income_to):
            pt = slab.amount_per_month
            break

    annual_projection = project_tds(
        fy,
        regime,
        AnnualIncome(gross_annual=gross * 12),
        declarations or Declarations(),
        t,
        months_elapsed=months_elapsed,
        tds_deducted_so_far=tds_deducted_so_far,
    )
    tds = annual_projection.monthly_tds

    earnings = {
        "basic": emp.basic,
        "hra": emp.hra,
        "special": emp.special,
        "variable": emp.variable,
    }
    deductions = {"lop": lop, "pf": pf, "esi": esi, "pt": pt, "tds": tds}
    net = round2(gross - lop - pf - esi - pt - tds)

    return PayrollLine(
        emp_id=emp.emp_id, earnings=earnings, deductions=deductions, gross=gross, net=net
    )


def compute_payroll(
    snapshot: PayrollSnapshot,
    tables: TaxTables,
    *,
    fy: str,
    regime_by_emp: dict[str, str] | None = None,
    declarations_by_emp: dict[str, Declarations] | None = None,
    tds_deducted_so_far_by_emp: dict[str, Decimal] | None = None,
    months_elapsed: int = 0,
) -> PayrollRegister:
    attendance_by_emp = {a.emp_id: a for a in snapshot.attendance}
    regime_by_emp = regime_by_emp or {}
    declarations_by_emp = declarations_by_emp or {}
    tds_so_far = tds_deducted_so_far_by_emp or {}

    lines: list[PayrollLine] = []
    for emp in snapshot.employees:
        att = attendance_by_emp.get(emp.emp_id) or Attendance(
            emp_id=emp.emp_id, days_in_month=30, lop_days=Decimal("0")
        )
        lines.append(
            compute_line(
                emp,
                att,
                tables,
                fy=fy,
                regime=regime_by_emp.get(emp.emp_id, "new"),
                declarations=declarations_by_emp.get(emp.emp_id),
                tds_deducted_so_far=tds_so_far.get(emp.emp_id, Decimal("0")),
                months_elapsed=months_elapsed,
            )
        )

    totals: dict[str, Decimal] = {"gross": Decimal("0"), "net": Decimal("0")}
    for line in lines:
        totals["gross"] += line.gross
        totals["net"] += line.net
        for key, val in line.deductions.items():
            totals[key] = totals.get(key, Decimal("0")) + val
    totals = {k: round2(v) for k, v in totals.items()}

    return PayrollRegister(
        month=snapshot.month,
        snapshot_id=snapshot.snapshot_id,
        lines=tuple(lines),
        totals=totals,
        tax_table_version=tables.version,
    )
