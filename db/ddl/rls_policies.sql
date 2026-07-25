-- Reference copy — authoritative version lives in
-- migrations/versions/0009_rls_and_views.py (upgrade()). Keep in sync on change.
--
-- Defense-in-depth behind MCP scope checks (doc 09 §1, doc 11 §7). Policies
-- read two session GUCs the repo layer sets per request from the caller's
-- verified Principal: awp.principal_roles (comma-separated), awp.principal_emp_id.

ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
CREATE POLICY candidates_role_scope ON candidates
USING (current_setting('awp.principal_roles', true) ~ 'hr_head|hr|admin_head|director|ceo');

ALTER TABLE employees ENABLE ROW LEVEL SECURITY;
CREATE POLICY employees_role_scope ON employees
USING (
    current_setting('awp.principal_roles', true) ~ 'admin_head|admin|director|ceo|hr_head|hr'
    OR emp_id = current_setting('awp.principal_emp_id', true)
);

ALTER TABLE comp_structures ENABLE ROW LEVEL SECURITY;
CREATE POLICY comp_structures_role_scope ON comp_structures
USING (
    current_setting('awp.principal_roles', true) ~ 'finance_head|finance|director|ceo|hr_head'
    OR emp_id = current_setting('awp.principal_emp_id', true)
);

ALTER TABLE payroll_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY payroll_runs_role_scope ON payroll_runs
USING (current_setting('awp.principal_roles', true) ~ 'finance_head|finance|director|ceo');

ALTER TABLE tickets ENABLE ROW LEVEL SECURITY;
CREATE POLICY tickets_confidential_scope ON tickets
USING (
    confidential = false
    OR current_setting('awp.principal_roles', true) ~ 'support_lead|hr_head|admin_head|director|ceo'
);
