-- Reference copy — authoritative version lives in
-- migrations/versions/0009_rls_and_views.py (upgrade()). Keep in sync on change.

CREATE VIEW v_trial_balance AS
SELECT account, SUM(dr) AS total_dr, SUM(cr) AS total_cr, SUM(dr) - SUM(cr) AS balance
FROM journal_lines
GROUP BY account;

CREATE VIEW v_open_tickets_by_priority AS
SELECT priority, category, count(*) AS open_count
FROM tickets
WHERE status NOT IN ('resolved', 'closed') AND deleted_at IS NULL
GROUP BY priority, category;
