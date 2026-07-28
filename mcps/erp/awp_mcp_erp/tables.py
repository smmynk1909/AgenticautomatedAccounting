"""SQLAlchemy Core tables for mcp-erp's aggregates — mirrors
`db/migrations/versions/0001_people.py`, `0002_assets.py`,
`0003_tickets_tasks.py`, `0008_platform_dashboard.py` exactly (those
migrations are the source of truth for the real Postgres DDL; keep this
file in sync with them on any change). Generic `JSON`/`ARRAY`-free types
here (not `postgresql.JSONB`) so the same table objects work against both
sqlite (unit tests) and Postgres (prod) — see mcps/audit's tables.py for
the same pattern/rationale.
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


departments = Table(
    "departments",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("name", sa.String(120), nullable=False, unique=True),
    Column("head_emp_id", sa.String(20), nullable=True),
    *_audit_cols(),
)

skills_master = Table(
    "skills_master",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("name", sa.String(120), nullable=False, unique=True),
    Column("synonyms", JSON, nullable=False, default=list),
    Column("category", sa.String(60), nullable=True),
    *_audit_cols(),
)

salary_bands = Table(
    "salary_bands",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("grade", sa.String(20), nullable=False),
    Column("min", sa.Numeric(14, 2), nullable=False),
    Column("mid", sa.Numeric(14, 2), nullable=False),
    Column("max", sa.Numeric(14, 2), nullable=False),
    Column("currency", sa.String(3), nullable=False, server_default="INR"),
    Column("effective_from", sa.Date(), nullable=False),
    *_audit_cols(),
)

roles = Table(
    "roles",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("title", sa.String(160), nullable=False),
    Column("grade", sa.String(20), nullable=False),
    Column("dept_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=False),
    Column("salary_band_id", sa.String(36), sa.ForeignKey("salary_bands.id"), nullable=True),
    Column("role_profile", JSON, nullable=False, default=dict),
    *_audit_cols(),
)

candidates = Table(
    "candidates",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("source", sa.String(60), nullable=False),
    Column("profile", JSON, nullable=False, default=dict),
    Column("resume_uri", sa.Text(), nullable=True),
    Column("status", sa.String(30), nullable=False, server_default="sourced"),
    Column("consent", JSON, nullable=False, default=dict),
    Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    *_audit_cols(),
)

employees = Table(
    "employees",
    metadata,
    Column("emp_id", sa.String(20), primary_key=True),
    Column("candidate_id", sa.String(36), sa.ForeignKey("candidates.id"), nullable=True),
    Column("name", sa.String(160), nullable=False),
    Column("contact_encrypted", sa.LargeBinary(), nullable=True),
    Column("dept_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=False),
    Column("role_id", sa.String(36), sa.ForeignKey("roles.id"), nullable=False),
    Column("manager_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=True),
    Column("grade", sa.String(20), nullable=False),
    Column("status", sa.String(20), nullable=False, server_default="active"),
    Column("join_date", sa.Date(), nullable=False),
    Column("exit_date", sa.Date(), nullable=True),
    Column("skills", JSON, nullable=False, default=list),
    Column("docs", JSON, nullable=False, default=dict),
    Column("comp_structure_id", sa.String(36), nullable=True),
    *_audit_cols(),
)

comp_structures = Table(
    "comp_structures",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
    Column("components_encrypted", sa.LargeBinary(), nullable=True),
    Column("effective_from", sa.Date(), nullable=False),
    *_audit_cols(),
)

assets = Table(
    "assets",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("type", sa.String(40), nullable=False),
    Column("make_model", sa.String(160), nullable=False),
    Column("serial", sa.String(80), nullable=True, unique=True),
    Column("purchase_date", sa.Date(), nullable=False),
    Column("value", sa.Numeric(14, 2), nullable=False),
    Column("warranty_till", sa.Date(), nullable=True),
    Column("amc_ref", sa.String(80), nullable=True),
    Column("status", sa.String(20), nullable=False, server_default="in_stock"),
    Column("location", sa.String(120), nullable=True),
    *_audit_cols(),
)

asset_assignments = Table(
    "asset_assignments",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("asset_id", sa.String(36), sa.ForeignKey("assets.id"), nullable=False),
    Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
    Column("issued_at", sa.DateTime(timezone=True), nullable=True),
    Column("ack_at", sa.DateTime(timezone=True), nullable=True),
    Column("returned_at", sa.DateTime(timezone=True), nullable=True),
    Column("condition", JSON, nullable=False, default=dict),
    *_audit_cols(),
)

entitlement_matrix = Table(
    "entitlement_matrix",
    metadata,
    Column("grade", sa.String(20), primary_key=True),
    Column("asset_type", sa.String(40), primary_key=True),
    Column("spec", sa.String(200), nullable=False),
    Column("policy_id", sa.String(60), nullable=False),
    *_audit_cols(),
)

tickets = Table(
    "tickets",
    metadata,
    Column("ticket_id", sa.String(24), primary_key=True),
    Column("channel", sa.String(20), nullable=False),
    Column("requester_type", sa.String(20), nullable=False),
    Column("requester_id", sa.String(40), nullable=False),
    Column("category", sa.String(40), nullable=False),
    Column("subcategory", sa.String(60), nullable=True),
    Column("priority", sa.String(2), nullable=False, server_default="P3"),
    Column("status", sa.String(20), nullable=False, server_default="new"),
    Column("assignee_type", sa.String(20), nullable=True),
    Column("assignee_id", sa.String(40), nullable=True),
    Column("parent_ticket_id", sa.String(24), sa.ForeignKey("tickets.ticket_id"), nullable=True),
    Column("linked_ticket_ids", JSON, nullable=False, default=list),
    Column("sla_first_response_due", sa.DateTime(timezone=True), nullable=True),
    Column("sla_resolution_due", sa.DateTime(timezone=True), nullable=True),
    Column("summary_current", sa.Text(), nullable=False, server_default=""),
    Column("resolution", JSON, nullable=False, default=dict),
    Column("confidential", sa.Boolean(), nullable=False, server_default=sa.false()),
    *_audit_cols(),
)

ticket_events = Table(
    "ticket_events",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("ticket_id", sa.String(24), sa.ForeignKey("tickets.ticket_id"), nullable=False),
    Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    Column("actor", sa.String(40), nullable=False),
    Column("type", sa.String(30), nullable=False),
    Column("body", JSON, nullable=False, default=dict),
)

orchestrator_tasks = Table(
    "orchestrator_tasks",
    metadata,
    Column("task_id", sa.String(36), primary_key=True),
    Column("parent", sa.String(36), sa.ForeignKey("orchestrator_tasks.task_id"), nullable=True),
    Column("agent", sa.String(10), nullable=False),
    Column("intent", sa.String(80), nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
    Column("status", sa.String(20), nullable=False, server_default="pending"),
    Column("priority", sa.String(2), nullable=False, server_default="P3"),
    Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
    Column("result", JSON, nullable=True),
    Column("trace_id", sa.String(36), nullable=False),
    *_audit_cols(),
)

dashboard_items = Table(
    "dashboard_items",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("audience_roles", JSON, nullable=False),
    Column("panel", sa.String(60), nullable=False),
    Column("severity", sa.String(20), nullable=False, server_default="info"),
    Column("title", sa.String(160), nullable=False),
    Column("body", sa.String(400), nullable=False),
    Column("action_link", sa.Text(), nullable=True),
    Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    Column("source_task_id", sa.String(36), nullable=True),
    Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)

# doc 09 §1 "Projects/Work" — mirrors db/migrations/versions/0005_projects_work.py
# exactly (see that migration's docstring: `sa.String(36)` id/FK columns,
# fixed as part of Sprint 9, same DEVIATIONS.md #11 pattern as every other
# table in this file).

projects = Table(
    "projects",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("client", sa.String(160), nullable=False),
    Column("sow_ref", sa.String(120), nullable=True),
    Column("status", sa.String(20), nullable=False, server_default="active"),
    Column("budget_hours", sa.Numeric(10, 2), nullable=True),
    Column("billing_type", sa.String(20), nullable=False, server_default="t_and_m"),
    # doc 05 §2.4/08 §8 (Sprint 10): which Gitea "owner/name" this
    # project's repo lives at — nullable, not every project has one.
    Column("repo_slug", sa.String(200), nullable=True),
    *_audit_cols(),
)

milestones = Table(
    "milestones",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
    Column("title", sa.String(200), nullable=False),
    Column("due", sa.Date(), nullable=True),
    Column("acceptance", JSON, nullable=False, default=dict),
    Column("status", sa.String(20), nullable=False, server_default="planned"),
    Column("invoice_trigger", sa.Boolean(), nullable=False, server_default=sa.false()),
    *_audit_cols(),
)

allocations = Table(
    "allocations",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
    Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
    Column("pct", sa.Numeric(5, 2), nullable=False),
    Column("from_date", sa.Date(), nullable=False),
    Column("to_date", sa.Date(), nullable=True),
    *_audit_cols(),
)

work_logs = Table(
    "work_logs",
    metadata,
    Column("id", sa.String(36), primary_key=True),
    Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
    Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
    Column("date", sa.Date(), nullable=False),
    Column("hours", sa.Numeric(4, 2), nullable=False),
    Column("task_ref", sa.String(120), nullable=True),
    Column("notes", sa.Text(), nullable=True),
    *_audit_cols(),
)
