"""0008_platform_dashboard — doc 09 §1 remaining "Platform" tables:
dashboard_items, kb_documents (Postgres-side metadata; vectors live in
Qdrant from Sprint 7 — doc 09 §1), agent_checkpoints (LangGraph
PostgresSaver), processed_keys (Redis-dedupe mirror for audit, doc 11 §7).

id/FK columns are `sa.String(36)`, not `pg.UUID` — see migration
0001_people's module docstring for why. `agent_checkpoints.task_id` matters
most here: `AgentApp.handle` (agents/_base) inserts `str(TaskEnvelope.task_id)`
on every single task, so this one is hit immediately, not a dormant risk.

Revision ID: 0008_platform_dashboard
Revises: 0007_audit_approvals
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008_platform_dashboard"
down_revision = "0007_audit_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_items",
        # doc 03 §2.4 push_dashboard_item shape.
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("audience_roles", pg.JSONB(), nullable=False),  # list[str]
        sa.Column("panel", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.String(400), nullable=False),
        sa.Column("action_link", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_task_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_dashboard_items_panel", "dashboard_items", ["panel"])
    op.create_index("ix_dashboard_items_expires", "dashboard_items", ["expires_at"])

    op.create_table(
        "kb_documents",
        # Postgres-side metadata row per chunk/doc; the embedding + hybrid
        # index itself lives in Qdrant (introduced Sprint 7, doc 09 §1
        # "Qdrant collections: resumes, support_kb, fin_kb, project_docs,
        # eng_kb, market_intel, code_{project}").
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("corpus", sa.String(60), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("acl_tags", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("department_scope", sa.String(20), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_kb_documents_corpus", "kb_documents", ["corpus"])

    op.create_table(
        "agent_checkpoints",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("graph", sa.String(40), nullable=False),
        sa.Column("state", sa.LargeBinary(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "processed_keys",
        # Postgres mirror of the Redis idempotency SETNX keys, so the audit
        # trail survives Redis restarts (doc 11 §7).
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("processed_keys")
    op.drop_table("agent_checkpoints")
    op.drop_index("ix_kb_documents_corpus", table_name="kb_documents")
    op.drop_table("kb_documents")
    op.drop_index("ix_dashboard_items_expires", table_name="dashboard_items")
    op.drop_index("ix_dashboard_items_panel", table_name="dashboard_items")
    op.drop_table("dashboard_items")
