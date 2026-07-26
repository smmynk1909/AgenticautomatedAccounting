"""0001_people — doc 09 §1 "People" tables.

Every id/FK column is `sa.String(36)`, not `pg.UUID(as_uuid=True)` — these
tables' Core mirror (mcps/erp/awp_mcp_erp/tables.py) deliberately uses
generic (non-Postgres-specific) column types throughout so the same table
objects work against sqlite in unit tests too, and every insert through it
serializes ids as `str(uuid4())`, not a native UUID — a Postgres UUID column
rejects that (`DatatypeMismatchError`). Was `pg.UUID` here, undetected until
this migration first ran against a real Postgres (this machine didn't have
Docker until now) — see migration 0003_tickets_tasks's `orchestrator_tasks`
comment for the same fix applied there.

Revision ID: 0001_people
Revises:
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001_people"
down_revision = None
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
    op.execute(
        "CREATE EXTENSION IF NOT EXISTS pgcrypto"
    )  # gen_random_uuid(), pgp_sym_encrypt for PII

    op.create_table(
        "departments",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "head_emp_id", sa.String(20), nullable=True
        ),  # FK to employees added after employees exists
        *_audit_cols(),
    )

    op.create_table(
        "skills_master",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        # JSONB, not `pg.ARRAY` — see the `linked_ticket_ids` comment in
        # migration 0003_tickets_tasks for why (Core mirror uses generic
        # `JSON`, which a Postgres ARRAY column rejects on insert).
        sa.Column("synonyms", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("category", sa.String(60), nullable=True),
        *_audit_cols(),
    )

    op.create_table(
        "salary_bands",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("min", sa.Numeric(14, 2), nullable=False),
        sa.Column("mid", sa.Numeric(14, 2), nullable=False),
        sa.Column("max", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("effective_from", sa.Date(), nullable=False),
        *_audit_cols(),
        sa.UniqueConstraint("grade", "effective_from", name="uq_salary_bands_grade_effective"),
    )

    op.create_table(
        "roles",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column(
            "dept_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=False
        ),
        sa.Column(
            "salary_band_id", sa.String(36), sa.ForeignKey("salary_bands.id"), nullable=True
        ),
        sa.Column("role_profile", pg.JSONB(), nullable=False, server_default="{}"),
        *_audit_cols(),
    )

    op.create_table(
        "candidates",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.String(60), nullable=False),
        sa.Column(
            "profile", pg.JSONB(), nullable=False, server_default="{}"
        ),  # CandidateProfile, doc 04 §2.2
        sa.Column("resume_uri", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="sourced"),
        sa.Column("consent", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_candidates_profile_gin", "candidates", ["profile"], postgresql_using="gin")
    # Must precede the index below — `gin_trgm_ops` doesn't exist until this
    # extension is created (only worked before when a real Postgres already
    # had it from `deploy/postgres/init.sql`'s separate `CREATE EXTENSION
    # pg_trgm`, which testcontainers-postgres — this migration applied to a
    # bare `postgres:16` container, no init.sql mounted — never runs).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_candidates_name_trgm ON candidates "
        "USING gin ((profile->>'name') gin_trgm_ops)"
    )

    op.create_table(
        "employees",
        # doc 09 §1: emp_id is a human-facing sequence identifier, not a UUID.
        # Allocation/formatting ("EMP-00001") is application-level (ADM-1
        # RegistryKeeper, doc 03 §2.2), not DB-generated.
        sa.Column("emp_id", sa.String(20), primary_key=True),
        sa.Column(
            "candidate_id", sa.String(36), sa.ForeignKey("candidates.id"), nullable=True
        ),
        sa.Column("name", sa.String(160), nullable=False),
        # pgcrypto-encrypted PII: contact stored as bytea via pgp_sym_encrypt at
        # the repository layer (doc 09 §1 "pgcrypto on comp + PII columns");
        # column type here is bytea, not jsonb, to hold the ciphertext.
        sa.Column("contact_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "dept_id", sa.String(36), sa.ForeignKey("departments.id"), nullable=False
        ),
        sa.Column("role_id", sa.String(36), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("manager_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=True),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("join_date", sa.Date(), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=True),
        # JSONB, not `pg.ARRAY` — see the `linked_ticket_ids` comment in
        # migration 0003_tickets_tasks for why.
        sa.Column("skills", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("docs", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "comp_structure_id", sa.String(36), nullable=True
        ),  # FK added after comp_structures exists
        *_audit_cols(),
    )
    op.create_index("ix_employees_dept_status", "employees", ["dept_id", "status"])

    op.create_foreign_key(
        "fk_departments_head_emp", "departments", "employees", ["head_emp_id"], ["emp_id"]
    )

    op.create_table(
        "comp_structures",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
        # pgcrypto-encrypted: salary component breakdown is comp data (doc 09
        # §1). Nullable like `employees.contact_encrypted` — real encryption
        # is repo-layer (Sprint 2+), not meaningful for synthetic fixtures
        # (see db/seed/generate_synthetic.py's seed_employees, which stores
        # None here deliberately). Was `nullable=False` here — drifted from
        # this table's own Core mirror (mcps/erp/awp_mcp_erp/tables.py,
        # already `nullable=True`) — fixed since this migration had never
        # been applied to a real Postgres before now.
        sa.Column("components_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        *_audit_cols(),
    )
    op.create_index("ix_comp_structures_emp", "comp_structures", ["emp_id", "effective_from"])

    op.create_foreign_key(
        "fk_employees_comp_structure", "employees", "comp_structures", ["comp_structure_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_employees_comp_structure", "employees", type_="foreignkey")
    op.drop_table("comp_structures")
    op.drop_constraint("fk_departments_head_emp", "departments", type_="foreignkey")
    op.drop_index("ix_employees_dept_status", table_name="employees")
    op.drop_table("employees")
    op.execute("DROP INDEX IF EXISTS ix_candidates_name_trgm")
    op.drop_index("ix_candidates_profile_gin", table_name="candidates")
    op.drop_table("candidates")
    op.drop_table("roles")
    op.drop_table("salary_bands")
    op.drop_table("skills_master")
    op.drop_table("departments")
