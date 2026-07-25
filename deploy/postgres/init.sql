-- Runs once, on first container start (docker-entrypoint-initdb.d), before
-- any Alembic migration. Creates extensions early so a superuser session is
-- guaranteed (the app DB user in later environments may not have CREATE
-- EXTENSION rights) — migration 0001_people also does this with
-- IF NOT EXISTS, so this is belt-and-suspenders, not load-bearing.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
