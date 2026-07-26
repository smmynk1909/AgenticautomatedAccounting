"""fincore/reconcile.py — doc 06 §2.2 "FinCore auto-match (amount+date+ref
heuristics)". Pure matching logic; `mcp-finance.reconcile_bank` is
responsible for loading the actual bank statement and ledger candidates and
persisting the result.

Confidence bands: exact amount + exact ref -> 1.0 (auto-matched); exact
amount + date within tolerance, no ref match -> 0.6 (suggestion, doc 06
§2.2: "LLM suggests matches for residuals with reasons -> human confirms");
anything else -> no match at all, left in the unmatched list.
"""

from __future__ import annotations

from decimal import Decimal

from fincore.models import BankTxnInput, LedgerCandidate, MatchResult

AUTO_MATCH_CONFIDENCE = Decimal("1.0")
SUGGESTION_CONFIDENCE = Decimal("0.6")


def match_bank_txns(
    bank_txns: list[BankTxnInput],
    candidates: list[LedgerCandidate],
    *,
    date_tolerance_days: int = 3,
) -> tuple[list[MatchResult], list[MatchResult], list[BankTxnInput]]:
    """Returns `(auto_matched, suggestions, unmatched)`. A candidate is
    consumed by at most one bank txn (first-fit in input order) so the same
    ledger entry can't satisfy two different bank rows."""
    remaining = list(candidates)
    auto_matched: list[MatchResult] = []
    suggestions: list[MatchResult] = []
    unmatched: list[BankTxnInput] = []

    for txn in bank_txns:
        best: tuple[LedgerCandidate, Decimal, str] | None = None
        for cand in remaining:
            if cand.amount != txn.amount:
                continue
            if abs((cand.date - txn.date).days) > date_tolerance_days:
                continue
            if txn.ref and cand.ref and txn.ref == cand.ref:
                best = (cand, AUTO_MATCH_CONFIDENCE, "amount+date+ref exact match")
                break
            if best is None:
                best = (cand, SUGGESTION_CONFIDENCE, "amount+date match, ref did not match")

        if best is None:
            unmatched.append(txn)
            continue

        cand, confidence, reason = best
        remaining.remove(cand)
        result = MatchResult(
            bank_txn_id=txn.id, entry_id=cand.entry_id, confidence=confidence, reason=reason
        )
        if confidence == AUTO_MATCH_CONFIDENCE:
            auto_matched.append(result)
        else:
            suggestions.append(result)

    return auto_matched, suggestions, unmatched
