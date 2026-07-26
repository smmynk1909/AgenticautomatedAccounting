from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fincore.ledger import LedgerError, post, trial_balance, validate_entry
from fincore.models import JournalEntry, JournalLine


def _entry(lines: tuple[JournalLine, ...], period: str = "2026-06") -> JournalEntry:
    return JournalEntry(date=date(2026, 6, 15), period=period, lines=lines, posted_by="test")


def test_balanced_entry_validates() -> None:
    e = _entry(
        (
            JournalLine(account="5001", dr=Decimal("1000.00")),
            JournalLine(account="1001", cr=Decimal("1000.00")),
        )
    )
    validate_entry(e)  # no raise


def test_unbalanced_entry_rejected() -> None:
    e = _entry(
        (
            JournalLine(account="5001", dr=Decimal("1000.00")),
            JournalLine(account="1001", cr=Decimal("999.00")),
        )
    )
    with pytest.raises(LedgerError):
        validate_entry(e)


def test_empty_entry_rejected() -> None:
    with pytest.raises(LedgerError):
        validate_entry(_entry(()))


def test_line_with_both_dr_and_cr_rejected() -> None:
    e = _entry((JournalLine(account="5001", dr=Decimal("10"), cr=Decimal("10")),))
    with pytest.raises(LedgerError):
        validate_entry(e)


def test_line_with_neither_dr_nor_cr_rejected() -> None:
    e = _entry((JournalLine(account="5001"), JournalLine(account="1001")))
    with pytest.raises(LedgerError):
        validate_entry(e)


def test_negative_amount_rejected() -> None:
    e = _entry((JournalLine(account="5001", dr=Decimal("-10")),))
    with pytest.raises(LedgerError):
        validate_entry(e)


def test_closed_period_rejected() -> None:
    e = _entry(
        (
            JournalLine(account="5001", dr=Decimal("100")),
            JournalLine(account="1001", cr=Decimal("100")),
        )
    )
    with pytest.raises(LedgerError):
        validate_entry(e, open_periods=frozenset({"2026-05"}))


def test_open_period_accepted() -> None:
    e = _entry(
        (
            JournalLine(account="5001", dr=Decimal("100")),
            JournalLine(account="1001", cr=Decimal("100")),
        )
    )
    validate_entry(e, open_periods=frozenset({"2026-06"}))


def test_unknown_account_rejected() -> None:
    e = _entry(
        (
            JournalLine(account="9999", dr=Decimal("100")),
            JournalLine(account="1001", cr=Decimal("100")),
        )
    )
    with pytest.raises(LedgerError):
        validate_entry(e, valid_accounts=frozenset({"1001", "5001"}))


def test_post_returns_totals() -> None:
    e = _entry(
        (
            JournalLine(account="5001", dr=Decimal("250.50")),
            JournalLine(account="1001", cr=Decimal("250.50")),
        )
    )
    posted = post(e)
    assert posted.total_dr == Decimal("250.50")
    assert posted.total_cr == Decimal("250.50")


def test_post_unbalanced_raises_and_nothing_returned() -> None:
    e = _entry((JournalLine(account="5001", dr=Decimal("100")),))
    with pytest.raises(LedgerError):
        post(e)


def test_trial_balance_nets_to_zero_across_all_accounts() -> None:
    entries = [
        _entry(
            (
                JournalLine(account="5001", dr=Decimal("100")),
                JournalLine(account="1001", cr=Decimal("100")),
            )
        ),
        _entry(
            (
                JournalLine(account="1002", dr=Decimal("50")),
                JournalLine(account="4001", cr=Decimal("50")),
            )
        ),
    ]
    balances = trial_balance(entries)
    assert sum(balances.values()) == Decimal("0")
    assert balances["5001"] == Decimal("100")
    assert balances["1001"] == Decimal("-100")
