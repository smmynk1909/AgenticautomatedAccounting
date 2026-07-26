"""fincore/ledger.py — doc 11 §4: `validate_entry` (balance, open period,
valid accounts), `post` (pure — the actual DB write happens in mcp-finance's
repo layer, "inside repo txn" per the doc's comment; this just validates and
packages the totals mcp-finance persists).

`open_periods`/`valid_accounts` are optional because fincore itself has no
database — mcp-finance's tool handler is the only caller with real periods/
accounts to check against; a bare balance check (no context) is still useful
on its own (e.g. property tests that only care about the balance invariant).
"""

from __future__ import annotations

from decimal import Decimal

from fincore.models import JournalEntry, PostedEntry, round2


class LedgerError(Exception):
    pass


def validate_entry(
    e: JournalEntry,
    *,
    open_periods: frozenset[str] | None = None,
    valid_accounts: frozenset[str] | None = None,
) -> None:
    if not e.lines:
        raise LedgerError("journal entry has no lines")

    for line in e.lines:
        if line.dr < 0 or line.cr < 0:
            raise LedgerError(f"account {line.account}: dr/cr must be non-negative")
        if line.dr > 0 and line.cr > 0:
            raise LedgerError(
                f"account {line.account}: a single line can't carry both a debit and a credit"
            )
        if line.dr == 0 and line.cr == 0:
            raise LedgerError(f"account {line.account}: line has neither a debit nor a credit")

    total_dr = round2(sum((line.dr for line in e.lines), Decimal("0")))
    total_cr = round2(sum((line.cr for line in e.lines), Decimal("0")))
    if total_dr != total_cr:
        raise LedgerError(f"entry does not balance: dr={total_dr} cr={total_cr}")

    if open_periods is not None and e.period not in open_periods:
        raise LedgerError(f"period {e.period!r} is not open")

    if valid_accounts is not None:
        unknown = {line.account for line in e.lines} - valid_accounts
        if unknown:
            raise LedgerError(f"unknown account(s): {sorted(unknown)}")


def post(
    e: JournalEntry,
    *,
    open_periods: frozenset[str] | None = None,
    valid_accounts: frozenset[str] | None = None,
) -> PostedEntry:
    validate_entry(e, open_periods=open_periods, valid_accounts=valid_accounts)
    total_dr = round2(sum((line.dr for line in e.lines), Decimal("0")))
    total_cr = round2(sum((line.cr for line in e.lines), Decimal("0")))
    return PostedEntry(entry=e, total_dr=total_dr, total_cr=total_cr)


def trial_balance(entries: list[JournalEntry]) -> dict[str, Decimal]:
    """Net dr-cr per account across every line in `entries` — the same
    "balances" check `get_trial_balance` exposes over real posted rows;
    exists here too so property tests can check the invariant (sum of all
    account balances == 0 for a balanced ledger) without a database."""
    balances: dict[str, Decimal] = {}
    for entry in entries:
        for line in entry.lines:
            balances[line.account] = balances.get(line.account, Decimal("0")) + line.dr - line.cr
    return {acct: round2(bal) for acct, bal in balances.items()}
