"""Dashboard item repository — doc 03 §2.4 exec dashboard feed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from awp_mcp_base.repo import RepoBase
from awp_shared.timeutil import ensure_aware_utc
from sqlalchemy import select

from awp_mcp_erp.tables import dashboard_items


class DashboardItemRepo(RepoBase):
    table = dashboard_items

    async def active_for_role(self, role: str, *, limit: int = 100) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        # audience_roles is a JSON array; containment isn't portable across
        # sqlite/Postgres in one query, so over-fetch recent rows and filter
        # in Python. Fine at dashboard-item volumes; revisit if this becomes
        # a hot path (real doc 09 §1 Postgres deployment could add a GIN
        # index + `?|` containment operator instead).
        stmt = select(self.table).order_by(self.table.c.created_at.desc()).limit(limit * 5)
        rows = (await self.session.execute(stmt)).mappings().all()

        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            expires_at = item["expires_at"]
            if expires_at is not None and ensure_aware_utc(expires_at) < now:
                continue
            if role in item["audience_roles"]:
                result.append(item)
            if len(result) >= limit:
                break
        return result
