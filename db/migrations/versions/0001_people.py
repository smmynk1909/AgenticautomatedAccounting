"""0001_people — doc 09 §1 "People" tables.

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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid(), pgp_sym_encrypt for PII

    op.create_table(
        "departments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("head_emp_id", sa.String(20), nullable=True),  # FK to employees added after employees exists
        *_audit_cols(),
    )

    op.create_table(
        "skills_master",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("synonyms", pg.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("category", sa.String(60), nullable=True),
        *_audit_cols(),
    )

    op.create_table(
        "salary_bands",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
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
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("dept_id", pg.UUID(as_uuid=True), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("salary_band_id", pg.UUID(as_uuid=True), sa.ForeignKey("salary_bands.id"), nullable=True),
        sa.Column("role_profile", pg.JSONB(), nullable=False, server_default="{}"),
        *_audit_cols(),
    )

    op.create_table(
        "candidates",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.String(60), nullable=False),
        sa.Column("profile", pg.JSONB(), nullable=False, server_default="{}"),  # CandidateProfile, doc 04 §2.2
        sa.Column("resume_uri", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="sourced"),
        sa.Column("consent", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_candidates_profile_gin", "candidates", ["profile"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_candidates_name_trgm ON candidates "
        "USING gin ((profile->>'name') gin_trgm_ops)"
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "employees",
        # doc 09 §1: emp_id is a human-facing sequence identifier, not a UUID.
        # Allocation/formatting ("EMP-00001") is application-level (ADM-1
        # RegistryKeeper, doc 03 §2.2), not DB-generated.
        sa.Column("emp_id", sa.String(20), primary_key=True),
        sa.Column("candidate_id", pg.UUID(as_uuid=True), sa.ForeignKey("candidates.id"), nullable=True),
        sa.Column("name", sa.String(160), nullable=False),
        # pgcrypto-encrypted PII: contact stored as bytea via pgp_sym_encrypt at
        # the repository layer (doc 09 §1 "pgcrypto on comp + PII columns");
        # column type here is bytea, not jsonb, to hold the ciphertext.
        sa.Column("contact_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("dept_id", pg.UUID(as_uuid=True), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("role_id", pg.UUID(as_uuid=True), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("manager_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=True),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("join_date", sa.Date(), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=True),
        sa.Column("skills", pg.ARRAY(pg.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("docs", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("comp_structure_id", pg.UUID(as_uuid=True), nullable=True),  # FK added after comp_structures exists
        *_audit_cols(),
    )
    op.create_index("ix_employees_dept_status", "employees", ["dept_id", "status"])

    op.create_foreign_key(
        "fk_departments_head_emp", "departments", "employees", ["head_emp_id"], ["emp_id"]
    )

    op.create_table(
        "comp_structures",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
        # pgcrypto-encrypted: salary component breakdown is comp data (doc 09 §1).
        sa.Column("components_encrypted", sa.LargeBinary(), nullable=False),
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
