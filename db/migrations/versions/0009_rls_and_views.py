"""0009_rls_and_views — doc 11 §7 row-level security (defense-in-depth
behind MCP scope checks, doc 09 §1) + reference reporting/dashboard views.

RLS policies read two session GUCs the repo layer (`mcps/_base/awp_mcp_base`)
sets per request from the caller's verified `Principal`:
  `awp.principal_roles`  — comma-separated role list (human callers)
  `awp.principal_emp_id` — the caller's own emp_id, for self-access rows

This is a second line of defense: MCP scope checks (`config/scopes.yaml`)
are the primary control and already deny unscoped calls before a query ever
runs; RLS means even a bug in that layer, or a direct psql session, still
can't read rows outside a caller's roles.

Revision ID: 0009_rls_and_views
Revises: 0008_platform_dashboard
Create Date: 2026-07-25
"""

from __future__ import annotations

from alembic import op

revision = "0009_rls_and_views"
down_revision = "0008_platform_dashboard"
branch_labels = None
depends_on = None

_HR_ROLES = "hr_head|hr|admin_head|director|ceo"
_FINANCE_ROLES = "finance_head|finance|director|ceo"
_ADMIN_ROLES = "admin_head|admin|director|ceo"


def upgrade() -> None:
    op.execute("ALTER TABLE candidates ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY candidates_role_scope ON candidates
        USING (current_setting('awp.principal_roles', true) ~ '{_HR_ROLES}')
        """
    )

    op.execute("ALTER TABLE employees ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY employees_role_scope ON employees
        USING (
            current_setting('awp.principal_roles', true) ~ '{_ADMIN_ROLES}|{_HR_ROLES}'
            OR emp_id = current_setting('awp.principal_emp_id', true)
        )
        """
    )

    op.execute("ALTER TABLE comp_structures ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY comp_structures_role_scope ON comp_structures
        USING (
            current_setting('awp.principal_roles', true) ~ '{_FINANCE_ROLES}|hr_head'
            OR emp_id = current_setting('awp.principal_emp_id', true)
        )
        """
    )

    op.execute("ALTER TABLE payroll_runs ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY payroll_runs_role_scope ON payroll_runs
        USING (current_setting('awp.principal_roles', true) ~ '{_FINANCE_ROLES}')
        """
    )

    op.execute("ALTER TABLE tickets ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tickets_confidential_scope ON tickets
        USING (
            confidential = false
            OR current_setting('awp.principal_roles', true)
                ~ 'support_lead|hr_head|admin_head|director|ceo'
        )
        """
    )

    # Reference reporting/dashboard views (db/ddl/*.sql carries copies for
    # ops/human reference — see that directory's docstring headers).
    op.execute(
        """
        CREATE VIEW v_trial_balance AS
        SELECT account, SUM(dr) AS total_dr, SUM(cr) AS total_cr, SUM(dr) - SUM(cr) AS balance
        FROM journal_lines
        GROUP BY account
        """
    )
    op.execute(
        """
        CREATE VIEW v_open_tickets_by_priority AS
        SELECT priority, category, count(*) AS open_count
        FROM tickets
        WHERE status NOT IN ('resolved', 'closed') AND deleted_at IS NULL
        GROUP BY priority, category
        """
    )
    op.execute(
        """
        CREATE VIEW v_dashboard_active AS
        SELECT * FROM dashboard_items
        WHERE expires_at IS NULL OR expires_at > now()
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_dashboard_active")
    op.execute("DROP VIEW IF EXISTS v_open_tickets_by_priority")
    op.execute("DROP VIEW IF EXISTS v_trial_balance")

    op.execute("DROP POLICY IF EXISTS tickets_confidential_scope ON tickets")
    op.execute("ALTER TABLE tickets DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS payroll_runs_role_scope ON payroll_runs")
    op.execute("ALTER TABLE payroll_runs DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS comp_structures_role_scope ON comp_structures")
    op.execute("ALTER TABLE comp_structures DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS employees_role_scope ON employees")
    op.execute("ALTER TABLE employees DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS candidates_role_scope ON candidates")
    op.execute("ALTER TABLE candidates DISABLE ROW LEVEL SECURITY")
