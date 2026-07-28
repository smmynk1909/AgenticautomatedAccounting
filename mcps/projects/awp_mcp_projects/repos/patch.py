"""Patch-artifact repository — doc 08 §8's `suggest_patch`."""

from __future__ import annotations

from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_projects.tables import patch_artifacts


class PatchArtifactRepo(RepoBase):
    table = patch_artifacts

    async def query(
        self, *, repo_slug: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        stmt = select(self.table)
        if repo_slug:
            stmt = stmt.where(self.table.c.repo_slug == repo_slug)
        stmt = stmt.order_by(self.table.c.created_at.desc()).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]
