"""0011_delivery_issues — mcp-projects (Sprint 9, doc 05 §2.3's Issue
object / doc 08's "issue-tracker CRUD"). `sa.String(36)` id/FK columns from
the start (DEVIATIONS.md #11's lesson already applied, not rediscovered).
Repo indexing/CodeAssist tables (if any end up needed) land with Sprint 10.

Revision ID: 0011_delivery_issues
Revises: 0010_comms_outbox
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0011_delivery_issues"
down_revision = "0010_comms_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_issues",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        # schedule|quality|scope|cost — doc 05 §2.3
        sa.Column("impact", sa.String(20), nullable=False),
        sa.Column("severity", sa.String(2), nullable=False, server_default="S3"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("owner", sa.String(40), nullable=True),
        sa.Column("mitigation_options", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("decision_needed_by", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_delivery_issues_project", "delivery_issues", ["project_id"])
    op.create_index("ix_delivery_issues_severity", "delivery_issues", ["severity", "status"])


def downgrade() -> None:
    op.drop_index("ix_delivery_issues_severity", table_name="delivery_issues")
    op.drop_index("ix_delivery_issues_project", table_name="delivery_issues")
    op.drop_table("delivery_issues")
