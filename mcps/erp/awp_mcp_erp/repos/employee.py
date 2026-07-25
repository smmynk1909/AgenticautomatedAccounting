"""Employee/people repositories — doc 09 §1 people aggregate."""

from __future__ import annotations

from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_erp.tables import (
    candidates,
    comp_structures,
    departments,
    employees,
    roles,
    salary_bands,
)


class EmployeeRepo(RepoBase):
    table = employees

    async def query(
        self,
        *,
        dept_id: str | None = None,
        status: str | None = None,
        manager_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.deleted_at.is_(None))
        if dept_id:
            stmt = stmt.where(self.table.c.dept_id == dept_id)
        if status:
            stmt = stmt.where(self.table.c.status == status)
        if manager_id:
            stmt = stmt.where(self.table.c.manager_id == manager_id)
        stmt = stmt.order_by(self.table.c.emp_id).offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


class CandidateRepo(RepoBase):
    table = candidates

    async def query(
        self, *, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.deleted_at.is_(None))
        if status:
            stmt = stmt.where(self.table.c.status == status)
        stmt = stmt.offset(offset).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def all_active(self) -> list[dict[str, Any]]:
        """Non-archived, non-deleted candidates — the dedupe-check pool (doc 03 §2.2)."""
        stmt = select(self.table).where(
            self.table.c.deleted_at.is_(None), self.table.c.archived_at.is_(None)
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


class DepartmentRepo(RepoBase):
    table = departments


class RoleRepo(RepoBase):
    table = roles


class SalaryBandRepo(RepoBase):
    table = salary_bands


class CompStructureRepo(RepoBase):
    table = comp_structures

    async def current_for_employee(self, emp_id: str) -> dict[str, Any] | None:
        stmt = (
            select(self.table)
            .where(self.table.c.emp_id == emp_id, self.table.c.deleted_at.is_(None))
            .order_by(self.table.c.effective_from.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).mappings().first()
        return dict(row) if row else None
