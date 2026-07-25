"""0006_training — doc 09 §1 "Training" tables.

Revision ID: 0006_training
Revises: 0005_projects_work
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0006_training"
down_revision = "0005_projects_work"
branch_labels = None
depends_on = None


def _audit_cols() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "training_catalog",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(120), nullable=True),
        sa.Column("skills", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("hours", sa.Numeric(6, 2), nullable=True),
        sa.Column("cost", sa.Numeric(14, 2), nullable=True),
        *_audit_cols(),
    )

    op.create_table(
        "training_plans",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
        sa.Column("items", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("approval_ref", sa.String(64), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_training_plans_emp", "training_plans", ["emp_id"])

    op.create_table(
        "training_progress",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "training_plan_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("training_plans.id"),
            nullable=False,
        ),
        sa.Column(
            "catalog_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("training_catalog.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="enrolled"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assessment_score", sa.Numeric(5, 2), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_training_progress_plan", "training_progress", ["training_plan_id"])


def downgrade() -> None:
    op.drop_index("ix_training_progress_plan", table_name="training_progress")
    op.drop_table("training_progress")
    op.drop_index("ix_training_plans_emp", table_name="training_plans")
    op.drop_table("training_plans")
    op.drop_table("training_catalog")
