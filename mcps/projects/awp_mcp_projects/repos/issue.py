"""Delivery issue repository — doc 05 §2.3's Issue object."""

from __future__ import annotations

from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_projects.tables import delivery_issues


class DeliveryIssueRepo(RepoBase):
    table = delivery_issues

    async def query(
        self,
        *,
        project_id: str | None = None,
        severity: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        stmt = select(self.table)
        if project_id:
            stmt = stmt.where(self.table.c.project_id == project_id)
        if severity:
            stmt = stmt.where(self.table.c.severity == severity)
        if status:
            stmt = stmt.where(self.table.c.status == status)
        stmt = stmt.order_by(self.table.c.severity, self.table.c.created_at).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]
