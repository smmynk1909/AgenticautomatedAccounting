"""Generic repository base — doc 11 §3: "DB access via repository classes per
aggregate ... no raw SQL in tools except reporting views."

Concrete repos (`EmployeeRepo`, `AssetRepo`, `TicketRepo`, `LedgerRepo`, ...)
land with the sprint that owns their aggregate; this base only encodes the
conventions doc 09 §1 fixes for every table: UUID/soft-delete columns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class RepoBase:
    table: Table  # subclasses bind their aggregate's table

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _pk_column(self) -> Any:
        return next(iter(self.table.primary_key.columns))

    async def get(self, pk: Any, *, include_deleted: bool = False) -> dict[str, Any] | None:
        stmt = select(self.table).where(self._pk_column() == pk)
        if not include_deleted and "deleted_at" in self.table.c:
            stmt = stmt.where(self.table.c.deleted_at.is_(None))
        row = (await self.session.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def insert(self, values: dict[str, Any]) -> Any:
        stmt = insert(self.table).values(**values).returning(self._pk_column())
        return (await self.session.execute(stmt)).scalar_one()

    async def update(self, pk: Any, values: dict[str, Any]) -> None:
        stmt = update(self.table).where(self._pk_column() == pk)
        if "updated_at" in self.table.c and "updated_at" not in values:
            values = {**values, "updated_at": datetime.now(UTC)}
        await self.session.execute(stmt.values(**values))

    async def soft_delete(self, pk: Any) -> None:
        # doc 09 §1: "deleted_at everywhere (soft delete)" — hard purge is a
        # human-run DBA script per doc 03 §2.2, never a repo method.
        if "deleted_at" not in self.table.c:
            raise NotImplementedError(f"{self.table.name} has no deleted_at column")
        await self.update(pk, {"deleted_at": datetime.now(UTC)})
