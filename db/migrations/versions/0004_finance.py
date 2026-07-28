"""0004_finance — doc 09 §1-2 "Finance" tables + doc 11 §7 balance trigger and
gapless invoice numbering.

id/FK columns are `sa.String(36)`, not `pg.UUID` — see migration 0001's
docstring / DEVIATIONS.md #11: `mcps/finance/awp_mcp_finance/tables.py`'s
SQLAlchemy Core mirror uses generic `sa.String(36)` so the same table
objects work against both sqlite (unit tests) and Postgres (prod);
`gen_random_uuid()` still works fine as a server_default on a
`sa.String(36)` column (Postgres casts it), already proven by migrations
0003/0008.

Revision ID: 0004_finance
Revises: 0003_tickets_tasks
Create Date: 2026-07-25
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004_finance"
down_revision = "0003_tickets_tasks"
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
        "accounts",
        # Chart of accounts (doc 09 §2) — code is the natural key, e.g. "1001".
        sa.Column("code", sa.String(10), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),  # asset|liability|equity|income|expense
        sa.Column("parent", sa.String(10), sa.ForeignKey("accounts.code"), nullable=True),
        *_audit_cols(),
    )

    op.create_table(
        "periods",
        sa.Column("period", sa.String(7), primary_key=True),  # "YYYY-MM"
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),  # open|closed
        *_audit_cols(),
    )

    op.create_table(
        "journal_entries",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("period", sa.String(7), sa.ForeignKey("periods.period"), nullable=False),
        sa.Column("ref", sa.String(120), nullable=True),
        sa.Column("posted_by", sa.String(40), nullable=False),
        sa.Column("approval_ref", sa.String(64), nullable=True),  # approvals.id / token jti
        *_audit_cols(),
    )
    op.create_index("ix_journal_entries_period", "journal_entries", ["period"])

    op.create_table(
        "journal_lines",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "entry_id", sa.String(36), sa.ForeignKey("journal_entries.id"), nullable=False
        ),
        sa.Column("account", sa.String(10), sa.ForeignKey("accounts.code"), nullable=False),
        sa.Column("dr", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("cr", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("cost_center", sa.String(40), nullable=True),
        sa.Column("meta", pg.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_journal_lines_account_entry", "journal_lines", ["account", "entry_id"])

    # doc 11 §7: DEFERRABLE INITIALLY DEFERRED constraint trigger — every
    # journal entry's lines must balance (Σdr = Σcr) by end-of-transaction,
    # not necessarily after every individual line insert.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_journal_balance() RETURNS TRIGGER AS $$
        DECLARE
            v_entry_id VARCHAR(36);
            v_sum_dr NUMERIC(14,2);
            v_sum_cr NUMERIC(14,2);
        BEGIN
            v_entry_id := COALESCE(NEW.entry_id, OLD.entry_id);
            SELECT COALESCE(SUM(dr), 0), COALESCE(SUM(cr), 0)
              INTO v_sum_dr, v_sum_cr
              FROM journal_lines WHERE entry_id = v_entry_id;
            IF v_sum_dr <> v_sum_cr THEN
                RAISE EXCEPTION
                    'journal entry % does not balance: dr=% cr=%', v_entry_id, v_sum_dr, v_sum_cr;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_balance
        AFTER INSERT OR UPDATE OR DELETE ON journal_lines
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION check_journal_balance();
        """
    )

    op.create_table(
        "payroll_runs",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("month", sa.String(7), nullable=False),  # "YYYY-MM"
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("register", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("approvals", pg.JSONB(), nullable=False, server_default="{}"),
        *_audit_cols(),
        sa.UniqueConstraint("month", name="uq_payroll_runs_month"),
    )

    op.create_table(
        "invoices",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # doc 11 §7: gapless per-FY sequential number, assigned inside
        # issue_invoice's transaction via a row lock on fy_counters — null
        # until issued (draft invoices have no number yet).
        sa.Column("number", sa.String(30), nullable=True, unique=True),
        sa.Column("fy", sa.String(7), nullable=False),  # "2026-27"
        sa.Column("client", sa.String(160), nullable=False),
        sa.Column("contract_ref", sa.String(80), nullable=True),
        sa.Column("lines", pg.JSONB(), nullable=False, server_default="[]"),
        sa.Column("gst", pg.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("due_date", sa.Date(), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_invoices_fy_status", "invoices", ["fy", "status"])

    op.create_table(
        "fy_counters",
        # doc 11 §7 gapless numbering support: `SELECT ... FOR UPDATE` this row
        # inside issue_invoice's transaction instead of a plain SEQUENCE
        # (sequences can skip values on rollback; this can't).
        sa.Column("fy", sa.String(7), primary_key=True),
        sa.Column("invoice_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "expenses",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("vendor", sa.String(160), nullable=True),
        sa.Column("doc_uri", sa.Text(), nullable=False),
        sa.Column(
            "extract", pg.JSONB(), nullable=False, server_default="{}"
        ),  # doc 06 §2.2 extraction shape
        sa.Column("account", sa.String(10), sa.ForeignKey("accounts.code"), nullable=True),
        sa.Column("cost_center", sa.String(40), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_review"),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        *_audit_cols(),
    )
    op.create_index("ix_expenses_status", "expenses", ["status"])

    op.create_table(
        "bank_txns",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("stmt_id", sa.String(80), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("ref", sa.String(160), nullable=True),
        sa.Column(
            "matched_entry",
            sa.String(36),
            sa.ForeignKey("journal_entries.id"),
            nullable=True,
        ),
        *_audit_cols(),
    )
    op.create_index("ix_bank_txns_stmt", "bank_txns", ["stmt_id"])

    op.create_table(
        "recurring_expenses",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("account", sa.String(10), sa.ForeignKey("accounts.code"), nullable=False),
        sa.Column("cost_center", sa.String(40), nullable=True),
        sa.Column("cadence", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("next_due", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_audit_cols(),
    )

    op.create_table(
        "tax_tables",
        # doc 06 §6: versioned YAML loaded here with effective-date ranges;
        # FinCore refuses to compute a period without a covering table version.
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "kind", sa.String(40), nullable=False
        ),  # it_slabs|pf|esi|pt_states|gst_rates|tds_sections
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("data", pg.JSONB(), nullable=False),
        *_audit_cols(),
        sa.UniqueConstraint("kind", "version", name="uq_tax_tables_kind_version"),
    )
    op.create_index("ix_tax_tables_kind_effective", "tax_tables", ["kind", "effective_from"])


def downgrade() -> None:
    op.drop_index("ix_tax_tables_kind_effective", table_name="tax_tables")
    op.drop_table("tax_tables")
    op.drop_table("recurring_expenses")
    op.drop_index("ix_bank_txns_stmt", table_name="bank_txns")
    op.drop_table("bank_txns")
    op.drop_index("ix_expenses_status", table_name="expenses")
    op.drop_table("expenses")
    op.drop_table("fy_counters")
    op.drop_index("ix_invoices_fy_status", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("payroll_runs")
    op.execute("DROP TRIGGER IF EXISTS trg_balance ON journal_lines")
    op.execute("DROP FUNCTION IF EXISTS check_journal_balance()")
    op.drop_index("ix_journal_lines_account_entry", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journal_entries_period", table_name="journal_entries")
    op.drop_table("journal_entries")
    op.drop_table("periods")
    op.drop_table("accounts")
