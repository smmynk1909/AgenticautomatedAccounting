"""0003_tickets_tasks — doc 07 §2 ticket model + doc 09 §1 "Tickets/Tasks".

Revision ID: 0003_tickets_tasks
Revises: 0002_assets
Create Date: 2026-07-25
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003_tickets_tasks"
down_revision = "0002_assets"
branch_labels = None
depends_on = None


def _audit_cols() -> list[sa.Column[Any]]:
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
        "tickets",
        # doc 07 §2: human-facing sequence "TKT-2026-00421"; app-allocated
        # (SUP-1a Intake), same convention as employees.emp_id.
        sa.Column("ticket_id", sa.String(24), primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False),  # chat|email|agent|dashboard
        sa.Column("requester_type", sa.String(20), nullable=False),  # employee|agent
        sa.Column("requester_id", sa.String(40), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("subcategory", sa.String(60), nullable=True),
        sa.Column("priority", sa.String(2), nullable=False, server_default="P3"),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("assignee_type", sa.String(20), nullable=True),  # agent|human
        sa.Column("assignee_id", sa.String(40), nullable=True),
        sa.Column(
            "parent_ticket_id", sa.String(24), sa.ForeignKey("tickets.ticket_id"), nullable=True
        ),
        # JSONB, not `pg.ARRAY` — this table's Core mirror
        # (mcps/erp/awp_mcp_erp/tables.py) deliberately uses generic
        # (non-Postgres-specific) column types throughout so the same table
        # object works against sqlite in unit tests too; a Postgres ARRAY
        # column can't accept the JSON `tickets.insert()` sends via that
        # mirror's `JSON` type (`DatatypeMismatchError`).
        sa.Column("linked_ticket_ids", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("sla_first_response_due", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_resolution_due", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary_current", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolution", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("confidential", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_audit_cols(),
    )
    op.create_index(
        "ix_tickets_status_category_priority", "tickets", ["status", "category", "priority"]
    )
    op.create_index("ix_tickets_parent", "tickets", ["parent_ticket_id"])

    op.create_table(
        "ticket_events",
        # append-only — no updated_at/deleted_at, doc 09 §1 explicit "(append-only)"
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ticket_id", sa.String(24), sa.ForeignKey("tickets.ticket_id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor", sa.String(40), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("body", pg.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_ticket_events_ticket", "ticket_events", ["ticket_id", "ts"])

    op.create_table(
        "orchestrator_tasks",
        # String(36), not `pg.UUID` — this table's Core mirror
        # (mcps/erp/awp_mcp_erp/tables.py) deliberately uses generic
        # (non-Postgres-specific) column types throughout so the same table
        # object works against sqlite in unit tests too; `TaskEnvelope.task_id`
        # is also always serialized to `str(uuid)` before insert
        # (tools_tasks.py's `dispatch_task`), never passed as a native UUID —
        # a Postgres UUID column rejects that (`DatatypeMismatchError`).
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column(
            "parent",
            sa.String(36),
            sa.ForeignKey("orchestrator_tasks.task_id"),
            nullable=True,
        ),
        sa.Column("agent", sa.String(10), nullable=False),
        sa.Column("intent", sa.String(80), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.String(2), nullable=False, server_default="P3"),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", pg.JSONB(), nullable=True),
        sa.Column("trace_id", sa.String(36), nullable=False),
        *_audit_cols(),
    )
    op.create_index("ix_orchestrator_tasks_status", "orchestrator_tasks", ["status"])
    op.create_index("ix_orchestrator_tasks_trace", "orchestrator_tasks", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_orchestrator_tasks_trace", table_name="orchestrator_tasks")
    op.drop_index("ix_orchestrator_tasks_status", table_name="orchestrator_tasks")
    op.drop_table("orchestrator_tasks")
    op.drop_index("ix_ticket_events_ticket", table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_index("ix_tickets_parent", table_name="tickets")
    op.drop_index("ix_tickets_status_category_priority", table_name="tickets")
    op.drop_table("tickets")
