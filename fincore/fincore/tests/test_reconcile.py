from __future__ import annotations

from datetime import date
from decimal import Decimal

from fincore.models import BankTxnInput, LedgerCandidate
from fincore.reconcile import match_bank_txns


def test_exact_amount_date_ref_auto_matches() -> None:
    txns = [BankTxnInput(id="B1", date=date(2026, 6, 5), amount=Decimal("1000"), ref="INV-1")]
    candidates = [
        LedgerCandidate(entry_id="E1", date=date(2026, 6, 5), amount=Decimal("1000"), ref="INV-1")
    ]
    auto, suggestions, unmatched = match_bank_txns(txns, candidates)
    assert len(auto) == 1
    assert auto[0].bank_txn_id == "B1"
    assert auto[0].entry_id == "E1"
    assert not suggestions
    assert not unmatched


def test_amount_and_date_match_without_ref_is_a_suggestion() -> None:
    txns = [BankTxnInput(id="B1", date=date(2026, 6, 5), amount=Decimal("1000"), ref="WIRE-XYZ")]
    candidates = [
        LedgerCandidate(entry_id="E1", date=date(2026, 6, 6), amount=Decimal("1000"), ref="INV-1")
    ]
    auto, suggestions, unmatched = match_bank_txns(txns, candidates)
    assert not auto
    assert len(suggestions) == 1
    assert suggestions[0].confidence < Decimal("1.0")


def test_no_amount_match_is_unmatched() -> None:
    txns = [BankTxnInput(id="B1", date=date(2026, 6, 5), amount=Decimal("1000"))]
    candidates = [LedgerCandidate(entry_id="E1", date=date(2026, 6, 5), amount=Decimal("500"))]
    auto, suggestions, unmatched = match_bank_txns(txns, candidates)
    assert not auto
    assert not suggestions
    assert unmatched == txns


def test_date_outside_tolerance_is_unmatched() -> None:
    txns = [BankTxnInput(id="B1", date=date(2026, 6, 1), amount=Decimal("1000"))]
    candidates = [LedgerCandidate(entry_id="E1", date=date(2026, 6, 20), amount=Decimal("1000"))]
    auto, suggestions, unmatched = match_bank_txns(txns, candidates, date_tolerance_days=3)
    assert not auto and not suggestions
    assert unmatched == txns


def test_candidate_consumed_by_at_most_one_txn() -> None:
    txns = [
        BankTxnInput(id="B1", date=date(2026, 6, 5), amount=Decimal("1000")),
        BankTxnInput(id="B2", date=date(2026, 6, 5), amount=Decimal("1000")),
    ]
    candidates = [LedgerCandidate(entry_id="E1", date=date(2026, 6, 5), amount=Decimal("1000"))]
    auto, suggestions, unmatched = match_bank_txns(txns, candidates)
    matched_ids = {m.entry_id for m in (auto + suggestions)}
    assert matched_ids == {"E1"}
    assert len(unmatched) == 1
