"""Bank transaction repository — doc 06 §2.2."""

from __future__ import annotations

from awp_mcp_base.repo import RepoBase

from awp_mcp_finance.tables import bank_txns


class BankTxnRepo(RepoBase):
    table = bank_txns
