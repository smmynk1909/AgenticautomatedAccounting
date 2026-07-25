-- Reference copy — authoritative version lives in
-- migrations/versions/0009_rls_and_views.py (upgrade()). Keep in sync on change.
--
-- Per-role filtering on audience_roles (jsonb array containment) happens in
-- mcp-erp's get_dashboard query (Sprint 2), not baked into this view, since
-- it's parameterized per caller role — this view only removes expired items.

CREATE VIEW v_dashboard_active AS
SELECT * FROM dashboard_items
WHERE expires_at IS NULL OR expires_at > now();
