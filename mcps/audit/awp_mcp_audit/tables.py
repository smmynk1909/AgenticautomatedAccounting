"""`audit_events` / `audit_day_roots` — doc 09 §1 platform tables. Defined
here (not in `db/`) because mcp-audit is the sole owner/writer of this
aggregate; `db/migrations` creates the matching DDL for the real Postgres
instance (doc 11 §7's convention: UUID pk, `created_at`, no soft-delete —
audit rows are append-only, never updated or deleted).
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

audit_events = Table(
    "audit_events",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("day", String(10), nullable=False, index=True),  # "YYYY-MM-DD" (UTC), chain grouping key
    Column("agent_id", String(64), nullable=False),
    Column("server", String(64), nullable=False),
    Column("tool", String(128), nullable=False),
    Column("input_hash", String(64), nullable=False),
    Column("output_hash", String(64), nullable=False),
    Column("refs", JSON, nullable=False, default=dict),
    Column("latency_ms", Float, nullable=False),
    Column("ok", Boolean, nullable=False),
    Column("error_code", String(32), nullable=True),
    # Write-time convenience snapshot only — verification (chain.py
    # record_hash_from_row / verifier.py) always recomputes from the other
    # columns' live values, never trusts this one (see chain.py docstring).
    Column("record_hash", String(64), nullable=False),
)

audit_day_roots = Table(
    "audit_day_roots",
    metadata,
    Column("day", String(10), primary_key=True),
    Column("root_hash", Text, nullable=False),
    Column("event_count", Integer, nullable=False),
    Column("computed_at", DateTime(timezone=True), nullable=False),
)
