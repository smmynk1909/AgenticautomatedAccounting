"""SQLAlchemy Core tables for mcp-projects — mirrors
`db/migrations/versions/0011_delivery_issues.py` and
`0013_codeassist.py`'s `patch_artifacts` exactly (those migrations are the
source of truth for the real Postgres DDL). Generic `JSON`, not
`postgresql.JSONB`, so the same table object works against both sqlite
(unit tests) and Postgres (prod) — same pattern as every other
`mcps/*/tables.py`.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import JSON, Column, MetaData, Table

metadata = MetaData()

delivery_issues = Table(
    "delivery_issues",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("project_id", sa.String(36), nullable=False),
    Column("description", sa.Text(), nullable=False),
    Column("impact", sa.String(20), nullable=False),
    Column("severity", sa.String(2), nullable=False, server_default="S3"),
    Column("status", sa.String(20), nullable=False, server_default="open"),
    Column("owner", sa.String(40), nullable=True),
    Column("mitigation_options", JSON, nullable=False, default=list),
    Column("decision_needed_by", sa.Date(), nullable=True),
    Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)

patch_artifacts = Table(
    "patch_artifacts",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("repo_slug", sa.String(200), nullable=False),
    Column("base_ref", sa.String(100), nullable=False),
    Column("patch_text", sa.Text(), nullable=False),
    Column("rationale", sa.Text(), nullable=False),
    Column("proposed_by", sa.String(40), nullable=False),
    Column("status", sa.String(20), nullable=False, server_default="proposed"),
    Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)
