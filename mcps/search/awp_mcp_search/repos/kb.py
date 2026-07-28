"""`kb_documents` repository — Postgres-side metadata row per chunk/doc
(doc 09 §1). One row per chunk upserted via `upsert_documents`; the
embedding vector + payload for retrieval live in Qdrant, keyed by the same
`id` so a Qdrant point maps 1:1 back to its metadata row.
"""

from __future__ import annotations

from typing import Any

from awp_mcp_base.repo import RepoBase
from sqlalchemy import select

from awp_mcp_search.tables import kb_documents


class KbDocumentRepo(RepoBase):
    table = kb_documents

    async def upsert(self, row: dict[str, Any]) -> str:
        existing = await self.get(row["id"])
        if existing is not None:
            await self.update(row["id"], {k: v for k, v in row.items() if k != "id"})
        else:
            await self.insert(row)
        return str(row["id"])

    async def get_many(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        stmt = select(self.table).where(
            self.table.c.id.in_(ids), self.table.c.deleted_at.is_(None)
        )
        rows = (await self.session.execute(stmt)).mappings().all()
        return {str(r["id"]): dict(r) for r in rows}
