"""SQLAlchemy Core tables for mcp-finance's aggregates — mirrors
`db/migrations/versions/0004_finance.py` exactly (that migration is the
source of truth for the real Postgres DDL; keep this file in sync with it
on any change). Generic `JSON`/`sa.String(36)` id/FK types here (not
`postgresql.JSONB`/`pg.UUID`) so the same table objects work against both
sqlite (unit tests) and Postgres (prod) — same pattern as every other
mcps/*/tables.py, see DEVIATIONS.md #11.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import JSON, Column, MetaData, Table

metadata = MetaData()


def _audit_cols() -> list[Column[Any]]:
    return [
        Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


accounts = Table(
    "accounts",
    metadata,
    Column("code", sa.String(10), primary_key=True),
    Column("name", sa.String(160), nullable=False),
    Column("type", sa.String(20), nullable=False),
    Column("parent", sa.String(10), sa.ForeignKey("accounts.code"), nullable=True),
    *_audit_cols(),
)

periods = Table(
    "periods",
    metadata,
    Column("period", sa.String(7), primary_key=True),
    Column("status", sa.String(10), nullable=False, server_default="open"),
    *_audit_cols(),
)

journal_entries = Table(
    "journal_entries",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("date", sa.Date(), nullable=False),
    Column("period", sa.String(7), sa.ForeignKey("periods.period"), nullable=False),
    Column("ref", sa.String(120), nullable=True),
    Column("posted_by", sa.String(40), nullable=False),
    Column("approval_ref", sa.String(64), nullable=True),
    *_audit_cols(),
)

journal_lines = Table(
    "journal_lines",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("entry_id", sa.String(36), sa.ForeignKey("journal_entries.id"), nullable=False),
    Column("account", sa.String(10), sa.ForeignKey("accounts.code"), nullable=False),
    Column("dr", sa.Numeric(14, 2), nullable=False, server_default="0"),
    Column("cr", sa.Numeric(14, 2), nullable=False, server_default="0"),
    Column("cost_center", sa.String(40), nullable=True),
    Column("meta", JSON, nullable=False, default=dict),
)

payroll_runs = Table(
    "payroll_runs",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("month", sa.String(7), nullable=False),
    Column("snapshot_id", sa.String(36), nullable=False),
    Column("register", JSON, nullable=False, default=dict),
    Column("status", sa.String(20), nullable=False, server_default="draft"),
    Column("approvals", JSON, nullable=False, default=dict),
    *_audit_cols(),
    sa.UniqueConstraint("month", name="uq_payroll_runs_month"),
)

invoices = Table(
    "invoices",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("number", sa.String(30), nullable=True, unique=True),
    Column("fy", sa.String(7), nullable=False),
    Column("client", sa.String(160), nullable=False),
    Column("contract_ref", sa.String(80), nullable=True),
    Column("lines", JSON, nullable=False, default=list),
    Column("gst", JSON, nullable=False, default=dict),
    Column("status", sa.String(20), nullable=False, server_default="draft"),
    Column("due_date", sa.Date(), nullable=True),
    *_audit_cols(),
)

fy_counters = Table(
    "fy_counters",
    metadata,
    Column("fy", sa.String(7), primary_key=True),
    Column("invoice_seq", sa.Integer(), nullable=False, server_default="0"),
    Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)

expenses = Table(
    "expenses",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("vendor", sa.String(160), nullable=True),
    Column("doc_uri", sa.Text(), nullable=False),
    Column("extract", JSON, nullable=False, default=dict),
    Column("account", sa.String(10), sa.ForeignKey("accounts.code"), nullable=True),
    Column("cost_center", sa.String(40), nullable=True),
    Column("status", sa.String(20), nullable=False, server_default="pending_review"),
    Column("confidence", sa.Numeric(4, 3), nullable=True),
    *_audit_cols(),
)

bank_txns = Table(
    "bank_txns",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("stmt_id", sa.String(80), nullable=False),
    Column("date", sa.Date(), nullable=False),
    Column("amount", sa.Numeric(14, 2), nullable=False),
    Column("ref", sa.String(160), nullable=True),
    Column("matched_entry", sa.String(36), sa.ForeignKey("journal_entries.id"), nullable=True),
    *_audit_cols(),
)

recurring_expenses = Table(
    "recurring_expenses",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("name", sa.String(160), nullable=False),
    Column("amount", sa.Numeric(14, 2), nullable=False),
    Column("account", sa.String(10), sa.ForeignKey("accounts.code"), nullable=False),
    Column("cost_center", sa.String(40), nullable=True),
    Column("cadence", sa.String(20), nullable=False, server_default="monthly"),
    Column("next_due", sa.Date(), nullable=True),
    Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    *_audit_cols(),
)

tax_tables = Table(
    "tax_tables",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("kind", sa.String(40), nullable=False),
    Column("version", sa.String(20), nullable=False),
    Column("effective_from", sa.Date(), nullable=False),
    Column("effective_to", sa.Date(), nullable=True),
    Column("data", JSON, nullable=False),
    *_audit_cols(),
    sa.UniqueConstraint("kind", "version", name="uq_tax_tables_kind_version"),
)
