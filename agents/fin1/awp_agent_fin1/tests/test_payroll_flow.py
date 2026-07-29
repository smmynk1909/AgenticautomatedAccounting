from __future__ import annotations

from awp_agent_fin1 import payroll_flow
from awp_agent_fin1.tests.conftest import FakeMCP


def test_fy_for_month_april_starts_new_fy() -> None:
    assert payroll_flow.fy_for_month("2026-04") == "2026-27"


def test_fy_for_month_march_belongs_to_prior_fy_start() -> None:
    assert payroll_flow.fy_for_month("2027-03") == "2026-27"


def test_fy_for_month_january() -> None:
    assert payroll_flow.fy_for_month("2027-01") == "2026-27"


async def test_gather_employees_filters_by_ids() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_employees"): {"employees": [{"emp_id": "EMP-1"}, {"emp_id": "EMP-2"}]}
        }
    )
    result = await payroll_flow.gather_employees_for_payroll(mcp, ["EMP-2"])
    assert [e["emp_id"] for e in result] == ["EMP-2"]


async def test_gather_employees_no_filter_returns_all() -> None:
    mcp = FakeMCP(
        handlers={
            ("erp", "query_employees"): {"employees": [{"emp_id": "EMP-1"}, {"emp_id": "EMP-2"}]}
        }
    )
    result = await payroll_flow.gather_employees_for_payroll(mcp, None)
    assert len(result) == 2


async def test_build_comp_snapshot_row_splits_band_mid() -> None:
    mcp = FakeMCP(handlers={("erp", "query_policies"): {"policies": [{"mid": "1200000"}]}})
    row = await payroll_flow.build_comp_snapshot_row(mcp, {"emp_id": "EMP-1", "grade": "E3"})
    # monthly = 1200000/12 = 100000; basic 50%=50000.00, hra 20%=20000.00, special 30%=30000.00
    assert row["basic"] == "50000.00"
    assert row["hra"] == "20000.00"
    assert row["special"] == "30000.00"


async def test_build_comp_snapshot_row_defaults_when_no_band_found() -> None:
    mcp = FakeMCP(handlers={("erp", "query_policies"): {"policies": []}})
    row = await payroll_flow.build_comp_snapshot_row(mcp, {"emp_id": "EMP-1", "grade": "E9"})
    assert row["emp_id"] == "EMP-1"
    assert float(row["basic"]) > 0


def test_salary_journal_lines_balance() -> None:
    from decimal import Decimal

    totals = {
        "gross": "100000",
        "lop": "0",
        "net": "80000",
        "pf": "12000",
        "esi": "0",
        "pt": "200",
        "tds": "7800",
    }
    lines = payroll_flow.salary_journal_lines(totals)
    dr = sum(Decimal(line.get("dr", "0")) for line in lines)
    cr = sum(Decimal(line.get("cr", "0")) for line in lines)
    assert dr == cr == Decimal("100000")


def test_salary_journal_lines_omits_zero_components() -> None:
    totals = {
        "gross": "50000",
        "lop": "0",
        "net": "50000",
        "pf": "0",
        "esi": "0",
        "pt": "0",
        "tds": "0",
    }
    lines = payroll_flow.salary_journal_lines(totals)
    accounts = {line["account"] for line in lines}
    assert accounts == {payroll_flow.ACCOUNT_SALARIES_EXPENSE, payroll_flow.ACCOUNT_SALARY_PAYABLE}
