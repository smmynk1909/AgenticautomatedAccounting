"""0005_projects_work — doc 09 §1 "Projects/Work" tables.

Revision ID: 0005_projects_work
Revises: 0004_finance
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005_projects_work"
down_revision = "0004_finance"
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
        "projects",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("client", sa.String(160), nullable=False),
        sa.Column("sow_ref", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("budget_hours", sa.Numeric(10, 2), nullable=True),
        sa.Column("billing_type", sa.String(20), nullable=False, server_default="t_and_m"),
        *_audit_cols(),
    )

    op.create_table(
        "milestones",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("due", sa.Date(), nullable=True),
        sa.Column("acceptance", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("invoice_trigger", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_audit_cols(),
    )
    op.create_index("ix_milestones_project_due", "milestones", ["project_id", "due"])

    op.create_table(
        "allocations",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
        sa.Column(
            "project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=False),
        sa.Column("to_date", sa.Date(), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_allocations_emp", "allocations", ["emp_id"])
    op.create_index("ix_allocations_project", "allocations", ["project_id"])

    op.create_table(
        "work_logs",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
        sa.Column(
            "project_id", pg.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hours", sa.Numeric(4, 2), nullable=False),
        sa.Column("task_ref", sa.String(120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_work_logs_emp_date", "work_logs", ["emp_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_work_logs_emp_date", table_name="work_logs")
    op.drop_table("work_logs")
    op.drop_index("ix_allocations_project", table_name="allocations")
    op.drop_index("ix_allocations_emp", table_name="allocations")
    op.drop_table("allocations")
    op.drop_index("ix_milestones_project_due", table_name="milestones")
    op.drop_table("milestones")
    op.drop_table("projects")
