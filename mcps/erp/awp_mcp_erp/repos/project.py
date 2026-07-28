"""Project/work repositories — doc 09 §1 "Projects/Work" aggregate."""

from __future__ import annotations

from datetime import date
from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_erp.tables import allocations, milestones, projects, work_logs


class ProjectRepo(RepoBase):
    table = projects

    async def query(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.deleted_at.is_(None))
        if status:
            stmt = stmt.where(self.table.c.status == status)
        stmt = stmt.order_by(self.table.c.client).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


class MilestoneRepo(RepoBase):
    table = milestones

    async def query(
        self,
        *,
        project_id: str | None = None,
        due_before: date | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.deleted_at.is_(None))
        if project_id:
            stmt = stmt.where(self.table.c.project_id == project_id)
        if due_before:
            stmt = stmt.where(self.table.c.due.is_not(None), self.table.c.due <= due_before)
        if status:
            stmt = stmt.where(self.table.c.status == status)
        stmt = stmt.order_by(self.table.c.due).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


class AllocationRepo(RepoBase):
    table = allocations

    async def query(
        self,
        *,
        emp_id: str | None = None,
        project_id: str | None = None,
        active_on: date | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.deleted_at.is_(None))
        if emp_id:
            stmt = stmt.where(self.table.c.emp_id == emp_id)
        if project_id:
            stmt = stmt.where(self.table.c.project_id == project_id)
        if active_on:
            stmt = stmt.where(
                self.table.c.from_date <= active_on,
                (self.table.c.to_date.is_(None)) | (self.table.c.to_date >= active_on),
            )
        stmt = stmt.order_by(self.table.c.from_date).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


class WorkLogRepo(RepoBase):
    table = work_logs

    async def query(
        self,
        *,
        emp_id: str | None = None,
        project_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.deleted_at.is_(None))
        if emp_id:
            stmt = stmt.where(self.table.c.emp_id == emp_id)
        if project_id:
            stmt = stmt.where(self.table.c.project_id == project_id)
        if date_from:
            stmt = stmt.where(self.table.c.date >= date_from)
        if date_to:
            stmt = stmt.where(self.table.c.date <= date_to)
        stmt = stmt.order_by(self.table.c.date).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]
