# Deviations from `docs/00`–`12`

Tracked so later sprints know exactly what to swap back when the "real"
infra becomes available, and why each shortcut is safe to take.

## 1. Model serving: Ollama instead of vLLM

Docs 00 §6/7, 01, 09 §3 specify vLLM (Linux+NVIDIA, AWQ quantization) behind
an nginx `model-gw`. This machine has no NVIDIA/Linux serving box, so
`serving/` targets **Ollama's OpenAI-compatible endpoint**
(`http://localhost:11434/v1`) directly — no nginx gateway container, Ollama
already multiplexes models by name over one port.

- `shared/awp_shared/llm.py` implements the exact `LLM` class contract from
  doc 11 §1.4 (`chat(messages, tools, guided_json, ...)`). Only the
  `base_url` and how `guided_json` is turned into a constraint differ
  internally (Ollama `format: json_schema` vs. vLLM `guided_json`). No
  caller code changes when vLLM is introduced later — swap `config/models.yaml`
  base URLs and the internal branch in `llm.py`.
- Model pool (`config/models.yaml`): `qwen2.5:7b-instruct` (M-GEN),
  `qwen2.5:3b-instruct` (M-SMALL), `qwen2.5-coder:7b-instruct` (M-CODE,
  pulled at Sprint 9/10), `bge-m3` (M-EMB, pulled at Sprint 7 when Qdrant
  lands). Sampling defaults unchanged from doc 01 §3.
- Ollama's tool-calling and `guided_json`/structured-output support is
  weaker than vLLM's `guided_decoding-backend outlines`. `llm.py` always
  does the repair-round-on-invalid-JSON dance from doc 11 §5.4 regardless of
  backend, so this is a quality risk to watch in evals (doc 09 §6), not a
  contract risk.

## 2. Auth: dev JWT instead of Keycloak

Docs 00 §7, 09 §4, 10 (AD-none but implied), 11 §1.2 specify Keycloak OIDC
for both human sessions and agent service-account JWTs, with `verify_jwt`
checking a JWKS endpoint.

Until Sprint 11 (hardening) stands up Keycloak, `shared/awp_shared/auth.py`:

- `verify_jwt` checks signature against a local HS256 secret
  (`AWP_DEV_JWT_SECRET` in `.env`) instead of fetching a JWKS.
- `mint_service_jwt(agent_id, scopes)` is unchanged — still returns a
  `Principal`-shaped JWT other code can't tell apart from a Keycloak one.
- Human principals come from `config/dev_users.yaml` (static list: id, roles)
  instead of a Keycloak realm — a `/api/dev/login` gateway route (Sprint 3)
  mints a session JWT for a chosen dev user, no password.
- **This is not safe for anything beyond a single trusted-developer machine.**
  Swapping to Keycloak later touches only `verify_jwt`'s key-source function
  and deletes `config/dev_users.yaml` / the dev-login route — no caller of
  `Principal`/`require_scopes` changes.

## 3. Trimmed Docker Compose, infra added per-sprint

`docs/09-DATA-INFRA-SECURITY.md` §3 lists one `docker-compose.yml` with every
service (Keycloak, Qdrant, Gitea, observability stack included) from day one.
This build introduces them when the sprint that needs them lands, which is
also roughly how the docs' own build sequence (doc 09 §8, doc 12 §5) is
ordered — this just makes it explicit in the compose files instead of
commenting services out:

| Compose file | Introduced | Adds |
|---|---|---|
| `deploy/docker-compose.dev.yml` | Sprint 1 (this build) | postgres, redis, minio, ollama, mcp-audit, mcp-approvals |
| same file, extended | Sprint 2–6 | mcp-erp, agent containers, gateway, web, mcp-finance |
| same file, extended | Sprint 7 | qdrant, mcp-search, mcp-hrsourcing |
| same file, extended | Sprint 9 | gitea, mcp-projects |
| same file, extended | Sprint 11 | keycloak, prometheus, grafana, loki, otel-collector |

## 4. Host Python 3.14, containers pinned to 3.12

Doc 11 pins Python 3.12 for all services. Host machine has 3.14 (Windows
Store alias) and no system Python on PATH otherwise. All MCP servers, agents,
and the gateway run inside `python:3.12-slim` containers per the pin — the
host version is irrelevant to them. Local dev tooling (running tests outside
containers, `db/seed/generate_synthetic.py` ad hoc) uses a `uv`-managed 3.12
venv (`uv python install 3.12`, `uv sync` in `pyproject.toml`) so the host
Python version never actually gets used.

## 6. MCP transport: plain HTTP+JSON instead of MCP JSON-RPC/SSE

Doc 00 §7/08 §0 specify Python `mcp` SDK (FastMCP) over HTTP-SSE, JSON-RPC
2.0. That SDK's exact client/server API isn't something to guess correctly
from training knowledge alone without a live install to check against, and
getting it subtly wrong would silently break every tool call.

Instead, `shared/awp_shared/mcpc.py` (`MCP.call`) and `mcps/_base` speak
plain HTTP+JSON, one POST per tool call (`POST {server_url}/tools/{tool}`,
JSON body = args, JSON response = result or `{"error": {...}}`). Every
cross-cutting convention doc 08 §0 actually requires — bearer JWT auth,
`X-Trace-Id`/`X-Idempotency-Key` headers, the structured error envelope,
approval-token gating, audit middleware — is implemented exactly as
specified; only the wire framing differs from real MCP JSON-RPC/SSE.

`mcps/_base/awp_mcp_base/pipeline.py` (`ToolPipeline`) and `server.py`
(`AwpMcpServer`) are written transport-agnostic on purpose: tool handlers are
plain `async def handler(payload: dict, ctx: Ctx) -> dict` functions, so
swapping the HTTP adapter for a real FastMCP/SSE adapter later touches only
the adapter layer, not tool logic, scopes, gates, or tests. Flagged as a
verification item for whichever sprint first needs true MCP-protocol
interop (e.g. an off-the-shelf MCP-aware IDE client for OPS-1 CodeAssist,
doc 05 §2.4) — internal agent-to-MCP-server calls never need it.

## 7. Config directory resolution: env var, not `__file__` traversal

`awp_shared/config.py`'s `CONFIG_DIR` used to be
`Path(__file__).resolve().parents[2] / "config"` — correct only in an
editable/source checkout. The container Dockerfiles (`mcps/*/Dockerfile`)
`pip install` each package non-editably, which copies files into
site-packages and breaks that assumption silently (resolves to some
site-packages ancestor, not the repo). Fixed by checking `AWP_CONFIG_DIR`
first, falling back to the old heuristic only for local dev. Every container
sets `AWP_CONFIG_DIR=/app/config` explicitly; local `uv run`/pytest leave it
unset and get the fallback.

## 8. Node 26 present, web app (Sprint 3+) not yet scaffolded

No deviation yet — noted so Sprint 3 doesn't re-check tooling. `web/`
(React 18 + Vite + Tailwind per doc 12 §2) targets Node ≥ 20; 26 is fine.
