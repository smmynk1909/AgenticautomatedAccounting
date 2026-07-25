"""0007_audit_approvals — mirrors mcps/audit/awp_mcp_audit/tables.py and
mcps/approvals/awp_mcp_approvals/tables.py exactly (those modules are the
source of truth for column names/semantics; keep this migration in sync with
them on any change). Append-only tables — no soft-delete columns, doc 09 §1.

Revision ID: 0007_audit_approvals
Revises: 0006_training
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0007_audit_approvals"
down_revision = "0006_training"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("server", sa.String(64), nullable=False),
        sa.Column("tool", sa.String(128), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("refs", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("record_hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_events_day", "audit_events", ["day"])
    op.create_index("ix_audit_events_agent_tool", "audit_events", ["agent_id", "tool"])

    op.create_table(
        "audit_day_roots",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("root_hash", sa.Text(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("gate", sa.String(64), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column("approver_roles", pg.JSONB(), nullable=False),
        sa.Column("n_required", sa.Integer(), nullable=False),
        sa.Column("approvals_received", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("token_jti", sa.String(64), nullable=True),
        sa.Column("rejected_by", sa.String(64), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approvals_gate_status", "approvals", ["gate", "status"])


def downgrade() -> None:
    op.drop_index("ix_approvals_gate_status", table_name="approvals")
    op.drop_table("approvals")
    op.drop_table("audit_day_roots")
    op.drop_index("ix_audit_events_agent_tool", table_name="audit_events")
    op.drop_index("ix_audit_events_day", table_name="audit_events")
    op.drop_table("audit_events")
