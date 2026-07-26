"""Ticket fabric repositories — doc 07 §2, doc 09 §1."""

from __future__ import annotations

from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_erp.tables import ticket_events, tickets


class TicketRepo(RepoBase):
    table = tickets

    async def query(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        assignee_id: str | None = None,
        requester_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.deleted_at.is_(None))
        if status:
            stmt = stmt.where(self.table.c.status == status)
        if category:
            stmt = stmt.where(self.table.c.category == category)
        if priority:
            stmt = stmt.where(self.table.c.priority == priority)
        if assignee_id:
            stmt = stmt.where(self.table.c.assignee_id == assignee_id)
        if requester_id:
            stmt = stmt.where(self.table.c.requester_id == requester_id)
        stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def children(self, parent_ticket_id: str) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.parent_ticket_id == parent_ticket_id)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


class TicketEventRepo(RepoBase):
    table = ticket_events

    async def for_ticket(self, ticket_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(self.table).where(self.table.c.ticket_id == ticket_id).order_by(self.table.c.ts)
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]
