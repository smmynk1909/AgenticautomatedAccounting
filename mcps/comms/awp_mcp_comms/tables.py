"""SQLAlchemy Core table for `comms_outbox` — mirrors
`db/migrations/versions/0010_comms_outbox.py` exactly (that migration is
the source of truth for the real Postgres DDL; keep this in sync with it on
any change). Generic types, not `postgresql.*`, so this table works against
both sqlite (unit tests) and Postgres (prod) — same pattern as
mcps/erp/awp_mcp_erp/tables.py.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import JSON, Column, MetaData, Table

metadata = MetaData()

comms_outbox = Table(
    "comms_outbox",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("kind", sa.String(20), nullable=False),
    Column("recipient_type", sa.String(20), nullable=False),
    Column("recipient_id", sa.String(80), nullable=True),
    Column("subject", sa.String(200), nullable=False),
    Column("body", sa.Text(), nullable=False),
    Column("refs", JSON, nullable=False, default=dict),
    Column("sent_by", sa.String(40), nullable=False),
    Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)
