"""Ledger repositories — doc 09 §1 Finance aggregate: accounts, periods,
journal_entries/journal_lines, plus the reporting queries (`get_trial_balance`,
`get_ledger`, `get_pnl`, `get_balance_sheet`) doc 08 §2 exposes as tools.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from awp_mcp_finance.tables import accounts, journal_entries, journal_lines, periods


class AccountRepo(RepoBase):
    table = accounts

    async def all_codes(self) -> frozenset[str]:
        rows = (await self.session.execute(select(accounts.c.code))).scalars().all()
        return frozenset(rows)

    async def get_type(self, code: str) -> str | None:
        row = (
            await self.session.execute(select(accounts.c.type).where(accounts.c.code == code))
        ).scalar_one_or_none()
        return row


class PeriodRepo(RepoBase):
    table = periods

    async def open_periods(self) -> frozenset[str]:
        rows = (
            (await self.session.execute(select(periods.c.period).where(periods.c.status == "open")))
            .scalars()
            .all()
        )
        return frozenset(rows)


class JournalRepo:
    """Combined entries+lines repo — a journal entry is always
    read/written as one unit (its lines have no independent identity doc
    09 §1 cares about outside their parent entry)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def post(
        self,
        *,
        entry_date: date,
        period: str,
        lines: list[dict[str, Any]],
        ref: str | None,
        posted_by: str,
        approval_ref: str | None,
    ) -> str:
        entry_id = str(uuid.uuid4())
        await self.session.execute(
            journal_entries.insert().values(
                id=entry_id,
                date=entry_date,
                period=period,
                ref=ref,
                posted_by=posted_by,
                approval_ref=approval_ref,
            )
        )
        for line in lines:
            await self.session.execute(
                journal_lines.insert().values(
                    id=str(uuid.uuid4()),
                    entry_id=entry_id,
                    account=line["account"],
                    dr=line.get("dr", Decimal("0")),
                    cr=line.get("cr", Decimal("0")),
                    cost_center=line.get("cost_center"),
                    meta=line.get("meta", {}),
                )
            )
        return entry_id

    async def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        entry_stmt = select(journal_entries).where(journal_entries.c.id == entry_id)
        entry_row = (await self.session.execute(entry_stmt)).mappings().first()
        if entry_row is None:
            return None
        line_stmt = select(journal_lines).where(journal_lines.c.entry_id == entry_id)
        line_rows = (await self.session.execute(line_stmt)).mappings().all()
        return {**dict(entry_row), "lines": [dict(r) for r in line_rows]}

    async def trial_balance(self, period: str) -> dict[str, Decimal]:
        stmt = (
            select(journal_lines.c.account, journal_lines.c.dr, journal_lines.c.cr)
            .join(journal_entries, journal_lines.c.entry_id == journal_entries.c.id)
            .where(journal_entries.c.period == period)
        )
        rows = (await self.session.execute(stmt)).all()
        balances: dict[str, Decimal] = {}
        for account, dr, cr in rows:
            balances[account] = balances.get(account, Decimal("0")) + Decimal(dr) - Decimal(cr)
        return balances

    async def ledger_for_account(
        self, account: str, *, date_from: date | None, date_to: date | None
    ) -> list[dict[str, Any]]:
        stmt = (
            select(
                journal_entries.c.id,
                journal_entries.c.date,
                journal_entries.c.ref,
                journal_lines.c.dr,
                journal_lines.c.cr,
                journal_lines.c.cost_center,
            )
            .join(journal_entries, journal_lines.c.entry_id == journal_entries.c.id)
            .where(journal_lines.c.account == account)
            .order_by(journal_entries.c.date)
        )
        if date_from is not None:
            stmt = stmt.where(journal_entries.c.date >= date_from)
        if date_to is not None:
            stmt = stmt.where(journal_entries.c.date <= date_to)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def balances_as_of(
        self,
        as_of: date,
        account_types: frozenset[str] | None,
        account_type_by_code: dict[str, str | None],
    ) -> dict[str, Decimal]:
        stmt = (
            select(journal_lines.c.account, journal_lines.c.dr, journal_lines.c.cr)
            .join(journal_entries, journal_lines.c.entry_id == journal_entries.c.id)
            .where(journal_entries.c.date <= as_of)
        )
        rows = (await self.session.execute(stmt)).all()
        balances: dict[str, Decimal] = {}
        for account, dr, cr in rows:
            acct_type = account_type_by_code.get(account)
            if account_types is not None and acct_type not in account_types:
                continue
            balances[account] = balances.get(account, Decimal("0")) + Decimal(dr) - Decimal(cr)
        return balances
