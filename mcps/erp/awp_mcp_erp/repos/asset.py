"""Asset repositories — doc 09 §1 assets aggregate."""

from __future__ import annotations

from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_erp.tables import asset_assignments, assets, entitlement_matrix


class AssetRepo(RepoBase):
    table = assets

    async def query(
        self, *, type_: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        stmt = select(self.table).where(self.table.c.deleted_at.is_(None))
        if type_:
            stmt = stmt.where(self.table.c.type == type_)
        if status:
            stmt = stmt.where(self.table.c.status == status)
        # FIFO on purchase_date — doc 03 §2.1 issuance pick order
        stmt = stmt.order_by(self.table.c.purchase_date.asc()).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]


class AssetAssignmentRepo(RepoBase):
    table = asset_assignments

    async def history_for_asset(self, asset_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(self.table)
            .where(self.table.c.asset_id == asset_id)
            .order_by(self.table.c.created_at)
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def open_assignment(self, asset_id: str) -> dict[str, Any] | None:
        stmt = select(self.table).where(
            self.table.c.asset_id == asset_id, self.table.c.returned_at.is_(None)
        )
        row = (await self.session.execute(stmt)).mappings().first()
        return dict(row) if row else None


class EntitlementRepo:
    """Composite-key aggregate (grade, asset_type) — doesn't fit RepoBase's
    single-column-PK assumption, so it isn't a RepoBase subclass."""

    def __init__(self, session: Any) -> None:
        self.session = session

    async def get_by_policy_id(self, policy_id: str) -> dict[str, Any] | None:
        stmt = select(entitlement_matrix).where(entitlement_matrix.c.policy_id == policy_id)
        row = (await self.session.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def get(self, grade: str, asset_type: str) -> dict[str, Any] | None:
        stmt = select(entitlement_matrix).where(
            entitlement_matrix.c.grade == grade, entitlement_matrix.c.asset_type == asset_type
        )
        row = (await self.session.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def query(self, *, grade: str | None = None) -> list[dict[str, Any]]:
        stmt = select(entitlement_matrix)
        if grade:
            stmt = stmt.where(entitlement_matrix.c.grade == grade)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]
