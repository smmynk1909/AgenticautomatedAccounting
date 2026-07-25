"""0002_assets — doc 09 §1 "Assets" tables.

Revision ID: 0002_assets
Revises: 0001_people
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002_assets"
down_revision = "0001_people"
branch_labels = None
depends_on = None


def _audit_cols() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("make_model", sa.String(160), nullable=False),
        sa.Column("serial", sa.String(80), nullable=True, unique=True),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(14, 2), nullable=False),
        sa.Column("warranty_till", sa.Date(), nullable=True),
        sa.Column("amc_ref", sa.String(80), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_stock"),
        sa.Column("location", sa.String(120), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_assets_type_status", "assets", ["type", "status"])

    op.create_table(
        "asset_assignments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asset_id", pg.UUID(as_uuid=True), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("emp_id", sa.String(20), sa.ForeignKey("employees.emp_id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("condition", pg.JSONB(), nullable=False, server_default="{}"),
        *_audit_cols(),
    )
    op.create_index("ix_asset_assignments_asset", "asset_assignments", ["asset_id"])
    op.create_index("ix_asset_assignments_emp", "asset_assignments", ["emp_id"])

    op.create_table(
        "entitlement_matrix",
        # composite natural key — mirrors config/entitlements.yaml (doc 03 §2.1),
        # DB copy exists so mcp-erp.get_policy can serve it without a config read
        sa.Column("grade", sa.String(20), primary_key=True),
        sa.Column("asset_type", sa.String(40), primary_key=True),
        sa.Column("spec", sa.String(200), nullable=False),
        sa.Column("policy_id", sa.String(60), nullable=False),
        *_audit_cols(),
    )


def downgrade() -> None:
    op.drop_table("entitlement_matrix")
    op.drop_index("ix_asset_assignments_emp", table_name="asset_assignments")
    op.drop_index("ix_asset_assignments_asset", table_name="asset_assignments")
    op.drop_table("asset_assignments")
    op.drop_index("ix_assets_type_status", table_name="assets")
    op.drop_table("assets")
