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
