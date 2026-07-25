"""Integration test: applies every migration to a real, throwaway Postgres
(testcontainers) and exercises the one piece of hand-written PL/pgSQL in this
sprint — the `trg_balance` deferred constraint trigger (doc 11 §7) — since
that's the highest-risk, least-mechanical DDL in the migration set and
nothing else in this test suite runs against real Postgres (mcps/audit and
mcps/approvals' own tests use sqlite for speed/portability, doc 12 §4's
"contract (mcps, testcontainers-postgres/redis)" step is *this* file).

Needs Docker. Skips (not fails) if Docker isn't available, so `make test` on
a Docker-less machine still passes — CI (GH Actions runners ship Docker)
is where this actually runs.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

DB_ROOT = Path(__file__).resolve().parents[1]

try:
    from testcontainers.postgres import PostgresContainer

    _TESTCONTAINERS_IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # pragma: no cover
    PostgresContainer = None  # type: ignore[assignment,misc]
    _TESTCONTAINERS_IMPORT_ERROR = exc


@pytest.fixture(scope="module")
def migrated_db_url() -> Iterator[str]:
    if PostgresContainer is None:
        pytest.skip(f"testcontainers not installed: {_TESTCONTAINERS_IMPORT_ERROR}")

    try:
        container = PostgresContainer("postgres:16")
        container.start()
    except Exception as exc:  # noqa: BLE001 - no Docker daemon, or can't pull the image
        pytest.skip(f"Docker not available for testcontainers: {exc}")

    try:
        async_url = container.get_connection_url(driver="asyncpg")

        cfg = Config(str(DB_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(DB_ROOT / "migrations"))
        import os

        os.environ["DATABASE_URL"] = async_url
        command.upgrade(cfg, "head")

        yield container.get_connection_url()  # sync (psycopg2) URL for assertions below
    finally:
        container.stop()


def test_expected_tables_and_columns_exist(migrated_db_url: str) -> None:
    engine = sa.create_engine(migrated_db_url)
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())

    expected = {
        "departments",
        "roles",
        "employees",
        "candidates",
        "skills_master",
        "salary_bands",
        "comp_structures",
        "assets",
        "asset_assignments",
        "entitlement_matrix",
        "tickets",
        "ticket_events",
        "orchestrator_tasks",
        "accounts",
        "periods",
        "journal_entries",
        "journal_lines",
        "payroll_runs",
        "invoices",
        "fy_counters",
        "expenses",
        "bank_txns",
        "recurring_expenses",
        "tax_tables",
        "projects",
        "milestones",
        "allocations",
        "work_logs",
        "training_catalog",
        "training_plans",
        "training_progress",
        "audit_events",
        "audit_day_roots",
        "approvals",
        "dashboard_items",
        "kb_documents",
        "agent_checkpoints",
        "processed_keys",
    }
    missing = expected - tables
    assert not missing, f"migrations did not create expected tables: {missing}"

    employee_cols = {c["name"] for c in inspector.get_columns("employees")}
    assert {"emp_id", "dept_id", "role_id", "manager_id", "deleted_at"} <= employee_cols

    journal_line_cols = {c["name"] for c in inspector.get_columns("journal_lines")}
    assert {"entry_id", "account", "dr", "cr"} <= journal_line_cols

    engine.dispose()


def test_trg_balance_accepts_balanced_entry(migrated_db_url: str) -> None:
    engine = sa.create_engine(migrated_db_url)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO periods (period, status) VALUES ('2026-07', 'open')"))
        conn.execute(
            sa.text("INSERT INTO accounts (code, name, type) VALUES ('9001', 'Test Bank', 'asset')")
        )
        conn.execute(
            sa.text(
                "INSERT INTO accounts (code, name, type) VALUES ('9002', 'Test Expense', 'expense')"
            )
        )
        entry_id = conn.execute(
            sa.text(
                "INSERT INTO journal_entries (date, period, posted_by) "
                "VALUES ('2026-07-15', '2026-07', 'test') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO journal_lines (entry_id, account, dr, cr) "
                "VALUES (:e, '9002', 100.00, 0)"
            ),
            {"e": entry_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO journal_lines (entry_id, account, dr, cr) "
                "VALUES (:e, '9001', 0, 100.00)"
            ),
            {"e": entry_id},
        )
    # no exception on commit == the trigger accepted a balanced entry
    engine.dispose()


def test_trg_balance_rejects_unbalanced_entry(migrated_db_url: str) -> None:
    engine = sa.create_engine(migrated_db_url)
    with pytest.raises(Exception, match="does not balance"):
        with engine.begin() as conn:
            entry_id = conn.execute(
                sa.text(
                    "INSERT INTO journal_entries (date, period, posted_by) "
                    "VALUES ('2026-07-16', '2026-07', 'test') RETURNING id"
                )
            ).scalar_one()
            conn.execute(
                sa.text(
                    "INSERT INTO journal_lines (entry_id, account, dr, cr) "
                    "VALUES (:e, '9002', 100.00, 0)"
                ),
                {"e": entry_id},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO journal_lines (entry_id, account, dr, cr) "
                    "VALUES (:e, '9001', 0, 50.00)"
                ),
                {"e": entry_id},
            )
            # transaction commits (and the DEFERRED trigger fires) on `with` exit
    engine.dispose()
