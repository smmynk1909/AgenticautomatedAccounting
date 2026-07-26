"""Golden-file style tests (doc 11 §4's testing contract) — expected figures
hand-derived from the exact formulas in doc 06 §2.1 step 2 / doc 11 §4 and
`fincore/tax_tables/*.yaml`'s 2026-27 tables, pinned here as a regression
baseline. See each test's inline arithmetic for the derivation.
"""

from __future__ import annotations

from decimal import Decimal

from fincore.models import Attendance, EmpComp, PayrollSnapshot, TaxTables
from fincore.payroll import compute_line, compute_payroll


def test_golden_single_line_ka_no_lop(tax_tables: TaxTables) -> None:
    emp = EmpComp(
        emp_id="EMP-1",
        grade="E3",
        basic=Decimal("50000"),
        hra=Decimal("20000"),
        special=Decimal("10000"),
        state="KA",
    )
    att = Attendance(emp_id="EMP-1", days_in_month=30, lop_days=Decimal("0"))

    line = compute_line(emp, att, tax_tables, fy="2026-27")

    # gross = 50000+20000+10000 = 80000
    assert line.gross == Decimal("80000.00")
    # pf = min(50000,15000)*0.12 = 1800
    assert line.deductions["pf"] == Decimal("1800.00")
    # gross(80000) > esi threshold(21000) -> no ESI
    assert line.deductions["esi"] == Decimal("0")
    # KA slab: gross>=15000 -> 200/month
    assert line.deductions["pt"] == Decimal("200.00")
    # no LOP days
    assert line.deductions["lop"] == Decimal("0")
    # taxable = 80000*12 - 50000 = 910000; new-regime slab tax = 46500;
    # +4% cess = 48360.00; /12 months = 4030.00
    assert line.deductions["tds"] == Decimal("4030.00")
    # net = 80000 - 0 - 1800 - 0 - 200 - 4030 = 73970.00
    assert line.net == Decimal("73970.00")


def test_golden_single_line_mh_esi_eligible(tax_tables: TaxTables) -> None:
    emp = EmpComp(
        emp_id="EMP-2",
        grade="E1",
        basic=Decimal("15000"),
        hra=Decimal("6000"),
        special=Decimal("0"),
        state="MH",
    )
    att = Attendance(emp_id="EMP-2", days_in_month=30, lop_days=Decimal("0"))

    line = compute_line(emp, att, tax_tables, fy="2026-27")

    assert line.gross == Decimal("21000.00")
    assert line.deductions["pf"] == Decimal("1800.00")
    # gross(21000) <= esi threshold(21000) -> ESI applies: 21000*0.0075
    assert line.deductions["esi"] == Decimal("157.50")
    # MH slab: gross>=10000 -> 200/month
    assert line.deductions["pt"] == Decimal("200.00")
    # taxable = 21000*12 - 50000 = 202000, entirely in the 0% new-regime slab
    assert line.deductions["tds"] == Decimal("0")
    assert line.net == Decimal("18842.50")


def test_pf_not_applied_when_opted_out(tax_tables: TaxTables) -> None:
    emp = EmpComp(
        emp_id="EMP-3",
        grade="E1",
        basic=Decimal("15000"),
        hra=Decimal("6000"),
        special=Decimal("0"),
        pf_opt_in=False,
        state="KA",
    )
    att = Attendance(emp_id="EMP-3", days_in_month=30, lop_days=Decimal("0"))
    line = compute_line(emp, att, tax_tables, fy="2026-27")
    assert line.deductions["pf"] == Decimal("0")


def test_lop_reduces_gross_pay(tax_tables: TaxTables) -> None:
    emp = EmpComp(
        emp_id="EMP-4",
        grade="E2",
        basic=Decimal("30000"),
        hra=Decimal("12000"),
        special=Decimal("0"),
        state="KA",
    )
    att = Attendance(emp_id="EMP-4", days_in_month=30, lop_days=Decimal("3"))
    line = compute_line(emp, att, tax_tables, fy="2026-27")
    # gross=42000; lop = round2(42000/30*3) = 4200.00
    assert line.deductions["lop"] == Decimal("4200.00")


def test_more_lop_days_never_increases_net_pay(tax_tables: TaxTables) -> None:
    """doc 11 §4's testing contract: "payroll monotonicity (more LOP => <= net)"."""
    emp = EmpComp(
        emp_id="EMP-5",
        grade="E2",
        basic=Decimal("40000"),
        hra=Decimal("16000"),
        special=Decimal("0"),
        state="KA",
    )
    att_low = Attendance(emp_id="EMP-5", days_in_month=30, lop_days=Decimal("1"))
    att_high = Attendance(emp_id="EMP-5", days_in_month=30, lop_days=Decimal("5"))
    fewer_lop = compute_line(emp, att_low, tax_tables, fy="2026-27")
    more_lop = compute_line(emp, att_high, tax_tables, fy="2026-27")
    assert more_lop.net <= fewer_lop.net


def test_compute_payroll_totals_sum_the_lines(tax_tables: TaxTables) -> None:
    employees = (
        EmpComp(
            emp_id="EMP-1",
            grade="E3",
            basic=Decimal("50000"),
            hra=Decimal("20000"),
            special=Decimal("10000"),
            state="KA",
        ),
        EmpComp(
            emp_id="EMP-2",
            grade="E1",
            basic=Decimal("15000"),
            hra=Decimal("6000"),
            special=Decimal("0"),
            state="MH",
        ),
    )
    attendance = (
        Attendance(emp_id="EMP-1", days_in_month=30, lop_days=Decimal("0")),
        Attendance(emp_id="EMP-2", days_in_month=30, lop_days=Decimal("0")),
    )
    snapshot = PayrollSnapshot(
        month="2026-06", snapshot_id="snap-1", employees=employees, attendance=attendance
    )

    register = compute_payroll(snapshot, tax_tables, fy="2026-27")

    assert len(register.lines) == 2
    assert register.totals["net"] == sum((line.net for line in register.lines), Decimal("0"))
    assert register.totals["gross"] == Decimal("101000.00")
    assert register.tax_table_version == "2026-27"


def test_missing_attendance_defaults_to_full_month(tax_tables: TaxTables) -> None:
    employees = (
        EmpComp(
            emp_id="EMP-9",
            grade="E1",
            basic=Decimal("20000"),
            hra=Decimal("8000"),
            special=Decimal("0"),
        ),
    )
    snapshot = PayrollSnapshot(
        month="2026-06", snapshot_id="snap-2", employees=employees, attendance=()
    )
    register = compute_payroll(snapshot, tax_tables, fy="2026-27")
    assert register.lines[0].deductions["lop"] == Decimal("0")
