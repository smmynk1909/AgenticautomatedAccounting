# Secrets rotation runbook

Doc 09 §3: "secrets in Docker secrets/Vault, never env-committed." Read
that as a target this dev build does not meet yet — every secret here
lives in `.env` (gitignored, but still a plaintext file on disk, not a
managed secrets store). This runbook covers rotating what exists today;
the honest gap (no Vault/Docker secrets) is called out at the end rather
than pretended away.

## What's a secret in this build

| Variable | Used by | Rotation impact |
|---|---|---|
| `AWP_DEV_JWT_SECRET` | HS256 signing for every agent's service-to-service JWT (`mint_service_jwt`) | Rotating invalidates every in-flight service token immediately — every MCP call mid-flight at rotation time fails auth until the calling container restarts with the new value. Restart order doesn't matter (all containers read the same `.env`); a rolling `docker compose up -d` picks it up per-container. |
| `AWP_APPROVAL_JWT_SECRET` | Signs HITL approval tokens (`awp_mcp_approvals/tokens.py`) — deliberately separate from the above so no agent-scoped JWT can ever forge an approval | Any approval token minted before rotation and not yet redeemed becomes invalid. Low blast radius (tokens are short-lived, `ttl_h` per `config/gates.yaml`) but worth checking `mcp-approvals`' pending-approval count before rotating. |
| `KEYCLOAK_CLIENT_SECRET` | Gateway's OIDC token exchange (`gateway/awp_gateway/routers/oidc_auth.py`) | Must be rotated in Keycloak's admin console (or `realm-export.json` + reimport) *and* `.env` together — mismatched values fail every login until both sides agree. |
| `KEYCLOAK_ADMIN_PASSWORD` | Keycloak's own bootstrap admin | Change via Keycloak admin console; `.env`'s copy is only read at first `--import-realm` boot, not continuously. |
| `POSTGRES_PASSWORD` | Every service's `DATABASE_URL` | Requires an actual `ALTER ROLE ... PASSWORD` against the running Postgres instance, then updating `.env` and restarting every dependent container — the highest-blast-radius rotation in this table, since every service reads it. |
| `GITEA_ADMIN_TOKEN` | `mcp-projects`' Gitea API calls (repo listing, file/diff/tree, CodeAssist repo tools) | Regenerate in Gitea's own UI/API, update `.env`, restart `mcp-projects`. |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin login (Sprint 11) | Change via Grafana's own UI/API or `.env` + container restart; anonymous Viewer access (dev-only, `GF_AUTH_ANONYMOUS_ENABLED`) doesn't need this secret at all — disable anonymous access before this matters in anything beyond a laptop dev environment. |

## Rotation steps (general shape)

1. Generate the new value (`openssl rand -hex 32` for the JWT secrets;
   the service's own UI/API for Keycloak/Postgres/Gitea/Grafana
   credentials).
2. Update `.env`.
3. For anything requiring a matching server-side change (Keycloak client
   secret, Postgres role password), make that change *first*, confirm it
   independently (e.g. `psql` with the new password before touching any
   container), then update `.env` to match.
4. `docker compose -f deploy/docker-compose.dev.yml up -d` — recreates
   any container whose environment changed; containers reading unchanged
   vars are left alone.
5. Verify: `docker compose ps` (nothing crash-looping), a real login
   (dev or Keycloak), and one real dispatched task per doc's own
   "live-verify, don't just review" discipline (this build's whole
   engineering culture, not new for this runbook).

## The real gap

Every value above sits in a `.env` file — readable by anyone with
filesystem access to the host, not centrally audited, not automatically
rotated, not access-controlled per-secret. That's fine for a single-
developer dev box; it is explicitly **not** what doc 09 §3 asks for
("Docker secrets/Vault") and is not production-appropriate. Standing up
a real secrets manager (Vault, or even Docker Swarm/Compose secrets as a
lighter first step) and switching every `${VAR}` reference in
`docker-compose.dev.yml` to a secrets mount is real infrastructure work,
sized similarly to the Keycloak swap-in (`DEVIATIONS.md` #22) — not done
here, named honestly as a pre-production requirement rather than glossed
over.
