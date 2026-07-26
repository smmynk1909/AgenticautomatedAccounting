"""SQLAlchemy Core table for `agent_checkpoints` — mirrors
`db/migrations/versions/0008_platform_dashboard.py` exactly (that migration
is the source of truth for the real Postgres DDL; keep this in sync with it
on any change). Generic types, not `postgresql.*`, so this table works
against both sqlite (unit tests) and Postgres (prod) — same pattern as
mcps/erp/awp_mcp_erp/tables.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import Column, MetaData, Table

metadata = MetaData()

agent_checkpoints = Table(
    "agent_checkpoints",
    metadata,
    Column("task_id", sa.String(36), primary_key=True),
    Column("graph", sa.String(40), nullable=False),
    Column("state", sa.LargeBinary(), nullable=False),
    Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)
