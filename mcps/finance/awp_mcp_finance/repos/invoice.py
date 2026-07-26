"""Invoice + FY-counter repositories — doc 09 §1, doc 11 §7's gapless
numbering ("SELECT ... FOR UPDATE this row inside issue_invoice's
transaction instead of a plain SEQUENCE").
"""

from __future__ import annotations

from datetime import UTC, datetime

from awp_mcp_base.repo import RepoBase
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from awp_mcp_finance.tables import fy_counters, invoices


class InvoiceRepo(RepoBase):
    table = invoices


class FyCounterRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_seq(self, fy: str) -> int:
        """Row-locks `fy_counters` for `fy` (creating it at 0 if missing)
        and returns the next sequence number — must be called inside the
        same DB transaction as the invoice-number assignment it backs, or
        the lock provides no gaplessness guarantee."""
        row = (
            (
                await self.session.execute(
                    select(fy_counters).where(fy_counters.c.fy == fy).with_for_update()
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            await self.session.execute(
                insert(fy_counters).values(fy=fy, invoice_seq=1, updated_at=datetime.now(UTC))
            )
            return 1

        next_seq = row["invoice_seq"] + 1
        await self.session.execute(
            update(fy_counters)
            .where(fy_counters.c.fy == fy)
            .values(invoice_seq=next_seq, updated_at=datetime.now(UTC))
        )
        return int(next_seq)
