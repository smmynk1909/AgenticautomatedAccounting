"""Task-bus state repository — doc 09 §1 orchestrator_tasks."""

from __future__ import annotations

from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_erp.tables import orchestrator_tasks


class OrchestratorTaskRepo(RepoBase):
    table = orchestrator_tasks

    async def children(self, parent_task_id: str) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.parent == parent_task_id)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def query(
        self,
        *,
        agent: str | None = None,
        status: str | None = None,
        top_level_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """`top_level_only`: rows with no `parent` — e.g. ORCH-0's own
        scheduler sweep (doc 02 §7) looking for open DAGs to reconcile, as
        opposed to the sub-tasks it dispatched under them."""
        stmt = select(self.table)
        if agent:
            stmt = stmt.where(self.table.c.agent == agent)
        if status:
            stmt = stmt.where(self.table.c.status == status)
        if top_level_only:
            stmt = stmt.where(self.table.c.parent.is_(None))
        stmt = stmt.order_by(self.table.c.created_at).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]
