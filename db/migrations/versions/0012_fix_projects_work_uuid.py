"""0012_fix_projects_work_uuid — Sprint 9 forward-fix for a live dev
database that already has 0005's original `pg.UUID` columns applied.

Editing 0005 in place (as DEVIATIONS.md #11 documents for 0001-0003) isn't
safe here: this dev box's Postgres has been running continuously since
Sprint 1-8's live verification and holds real accumulated data in tables
0005-0010 touch (tickets, dashboard_items, comms_outbox,
agent_checkpoints, ...) — downgrading past 0005 to re-apply it would walk
back through and re-create every one of those tables, discarding that
data. `projects`/`milestones`/`allocations`/`work_logs` themselves are
empty (no tool ever wrote to them before Sprint 9), so a plain
`ALTER COLUMN ... TYPE` is safe and loses nothing.

A fresh `alembic upgrade head` from an empty database never runs this
migration's `upgrade()` body at all — 0005 already creates the columns as
`sa.String(36)` directly (see its own docstring). This migration exists
solely to reconcile an already-migrated live database.

Revision ID: 0012_fix_projects_work_uuid
Revises: 0011_delivery_issues
Create Date: 2026-07-28
"""

from __future__ import annotations

from alembic import op

revision = "0012_fix_projects_work_uuid"
down_revision = "0011_delivery_issues"
branch_labels = None
depends_on = None

_ALTERS = [
    ("projects", "id"),
    ("milestones", "id"),
    ("milestones", "project_id"),
    ("allocations", "id"),
    ("allocations", "project_id"),
    ("work_logs", "id"),
    ("work_logs", "project_id"),
]

# Postgres's default auto-generated names for the unnamed FKs
# `sa.ForeignKey("projects.id")` created in 0005 — confirmed against the
# live DB's pg_constraint, not guessed (`<table>_<column>_fkey` happens to
# match Postgres's own default convention here, but that's not guaranteed
# for every constraint shape, so this was checked rather than assumed).
_PROJECT_ID_FKEYS = [
    ("milestones", "milestones_project_id_fkey"),
    ("allocations", "allocations_project_id_fkey"),
    ("work_logs", "work_logs_project_id_fkey"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # sqlite has no real column type system to fix — the Core mirror
        # already uses sa.String(36) there regardless of what this
        # migration's DDL says (see mcps/erp/awp_mcp_erp/tables.py).
        return
    # Postgres refuses to retype a PK column while an FK still references
    # it with a different type (`milestones_project_id_fkey cannot be
    # implemented: uuid and character varying`, hit live running this the
    # first time) — drop the FKs, alter every column, then recreate them.
    for table, fkey in _PROJECT_ID_FKEYS:
        op.drop_constraint(fkey, table, type_="foreignkey")
    for table, column in _ALTERS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE VARCHAR(36) USING {column}::text"
        )
    # `gen_random_uuid()` still works as a VARCHAR default (Postgres casts
    # uuid -> text for the DEFAULT expression) — no default-clause change
    # needed, only the two id columns' declared type.
    for table, fkey in _PROJECT_ID_FKEYS:
        op.create_foreign_key(fkey, table, "projects", ["project_id"], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table, fkey in _PROJECT_ID_FKEYS:
        op.drop_constraint(fkey, table, type_="foreignkey")
    for table, column in _ALTERS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE UUID USING {column}::uuid"
        )
    for table, fkey in _PROJECT_ID_FKEYS:
        op.create_foreign_key(fkey, table, "projects", ["project_id"], ["id"])
