"""SQLAlchemy Core table for mcp-search's aggregate — mirrors
`db/migrations/versions/0008_platform_dashboard.py`'s `kb_documents` table
exactly (Postgres-side metadata row per chunk/doc; the embedding + hybrid
index itself lives in Qdrant). Generic `JSON` here (not `postgresql.JSONB`,
which the migration source uses) so the same table object works against
both sqlite (unit tests) and Postgres (prod) — DEVIATIONS.md #11's
convention, same as every other `mcps/*/tables.py`.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import JSON, Column, MetaData, Table

metadata = MetaData()

kb_documents = Table(
    "kb_documents",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("corpus", sa.String(60), nullable=False),
    Column("title", sa.String(200), nullable=True),
    Column("acl_tags", JSON, nullable=False, default=list),
    Column("department_scope", sa.String(20), nullable=True),
    Column("as_of", sa.Date(), nullable=True),
    Column("source_uri", sa.Text(), nullable=True),
    Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
)
