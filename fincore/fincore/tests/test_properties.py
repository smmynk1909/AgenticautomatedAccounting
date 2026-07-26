"""Hypothesis property tests — doc 11 §4's testing contract: "TB balance
invariant, payroll monotonicity (more LOP => <= net), rounding = round-half-
up 2dp, regime comparison symmetric." The ledger balance invariant here is
the fincore-level half of doc 06 §7 acceptance test 2 ("fuzz 10k random
postings via API — zero unbalanced entries persisted") — the "via API" half
(concurrent `mcp-finance.post_journal` calls against a real DB) lives in
`mcps/finance/awp_mcp_finance/tests/`.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fincore.ledger import LedgerError, post, trial_balance, validate_entry
from fincore.models import (
    AnnualIncome,
    Attendance,
    Declarations,
    EmpComp,
    JournalEntry,
    JournalLine,
    round2,
)
from fincore.payroll import compute_line
from fincore.tables import load_tax_tables
from fincore.tax import compare_regimes

_TAX_TABLES = load_tax_tables(date(2026, 6, 15))

money = st.decimals(
    min_value="0.01", max_value="1000000", places=2, allow_nan=False, allow_infinity=False
)


@given(st.lists(money, min_size=1, max_size=5))
@settings(max_examples=1000, deadline=None)
def test_balanced_entries_always_post_and_never_unbalance(amounts: list[Decimal]) -> None:
    """Fuzz: a dr-side split into N sub-amounts against one cr line for the
    same total is balanced by construction — `post` must never reject it,
    and the resulting trial balance must always net to exactly zero."""
    total = round2(sum(amounts, Decimal("0")))
    if total == 0:
        return
    lines = tuple(JournalLine(account="5001", dr=amt) for amt in amounts) + (
        JournalLine(account="1001", cr=total),
    )
    entry = JournalEntry(date=date(2026, 6, 15), period="2026-06", lines=lines, posted_by="fuzz")

    posted = post(entry)
    assert posted.total_dr == posted.total_cr == total
    assert sum(trial_balance([entry]).values()) == Decimal("0")


@given(money, money)
@settings(max_examples=500, deadline=None)
def test_unequal_dr_cr_always_rejected(dr: Decimal, cr: Decimal) -> None:
    if dr == cr:
        return
    entry = JournalEntry(
        date=date(2026, 6, 15),
        period="2026-06",
        lines=(JournalLine(account="5001", dr=dr), JournalLine(account="1001", cr=cr)),
        posted_by="fuzz",
    )
    with pytest.raises(LedgerError):
        validate_entry(entry)


@given(
    st.decimals(min_value="-1000000", max_value="1000000", allow_nan=False, allow_infinity=False)
)
@settings(max_examples=500)
def test_round2_always_two_places_half_up(x: Decimal) -> None:
    result = round2(x)
    assert result == result.quantize(Decimal("0.01"))
    # Cross-check against an independent ROUND_HALF_UP computation.
    assert result == x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@given(
    basic=st.decimals(
        min_value="10000", max_value="200000", places=2, allow_nan=False, allow_infinity=False
    ),
    hra=st.decimals(
        min_value="0", max_value="100000", places=2, allow_nan=False, allow_infinity=False
    ),
    lop_low=st.integers(min_value=0, max_value=10),
    lop_extra=st.integers(min_value=0, max_value=15),
)
@settings(max_examples=200, deadline=None)
def test_more_lop_days_never_increases_net(
    basic: Decimal, hra: Decimal, lop_low: int, lop_extra: int
) -> None:
    emp = EmpComp(
        emp_id="EMP-FUZZ", grade="E2", basic=basic, hra=hra, special=Decimal("0"), state="KA"
    )
    lop_high = lop_low + lop_extra
    att_low = Attendance(emp_id="EMP-FUZZ", days_in_month=30, lop_days=Decimal(lop_low))
    att_high = Attendance(emp_id="EMP-FUZZ", days_in_month=30, lop_days=Decimal(lop_high))
    line_low = compute_line(emp, att_low, _TAX_TABLES, fy="2026-27")
    line_high = compute_line(emp, att_high, _TAX_TABLES, fy="2026-27")
    assert line_high.net <= line_low.net


@given(
    gross_annual=st.decimals(
        min_value="300000", max_value="5000000", places=2, allow_nan=False, allow_infinity=False
    )
)
@settings(max_examples=300, deadline=None)
def test_regime_comparison_agrees_with_min_of_both(gross_annual: Decimal) -> None:
    """doc 11 §4: "regime comparison symmetric" — `compare_regimes`'s
    `recommended` must always name whichever regime it itself computed the
    lower `annual_tax` for; there's no ordering-dependent asymmetry."""
    income = AnnualIncome(gross_annual=gross_annual)
    cmp = compare_regimes("2026-27", income, Declarations(), Declarations(), _TAX_TABLES)
    if cmp.old_regime_tax < cmp.new_regime_tax:
        assert cmp.recommended == "old"
    else:
        assert cmp.recommended == "new"
