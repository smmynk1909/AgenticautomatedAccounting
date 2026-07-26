from __future__ import annotations

from datetime import date
from decimal import Decimal

from fincore.cashflow import cashflow_model, first_negative_week


def test_running_balance_accumulates() -> None:
    rows = cashflow_model(
        Decimal("10000"),
        [
            (date(2026, 6, 1), Decimal("5000"), Decimal("3000"), ("payroll due",)),
            (date(2026, 6, 8), Decimal("1000"), Decimal("4000"), ()),
        ],
    )
    assert rows[0].net == Decimal("2000.00")
    assert rows[0].running_balance == Decimal("12000.00")
    assert rows[1].net == Decimal("-3000.00")
    assert rows[1].running_balance == Decimal("9000.00")


def test_first_negative_week_detects_funding_gap() -> None:
    rows = cashflow_model(
        Decimal("1000"),
        [
            (date(2026, 6, 1), Decimal("0"), Decimal("500"), ()),
            (date(2026, 6, 8), Decimal("0"), Decimal("600"), ()),
        ],
    )
    assert first_negative_week(rows) == date(2026, 6, 8)


def test_first_negative_week_none_when_always_positive() -> None:
    rows = cashflow_model(
        Decimal("10000"), [(date(2026, 6, 1), Decimal("1000"), Decimal("500"), ())]
    )
    assert first_negative_week(rows) is None


def test_empty_flows_returns_empty_rows() -> None:
    assert cashflow_model(Decimal("1000"), []) == []
