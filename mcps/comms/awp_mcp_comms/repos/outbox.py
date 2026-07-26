"""Outbox repository — doc 08 §1, doc 07 §4."""

from __future__ import annotations

from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_comms.tables import comms_outbox


class OutboxRepo(RepoBase):
    table = comms_outbox

    async def for_recipient(self, recipient_type: str, recipient_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(self.table)
            .where(
                self.table.c.recipient_type == recipient_type,
                self.table.c.recipient_id == recipient_id,
            )
            .order_by(self.table.c.created_at.desc())
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]
