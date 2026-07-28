.PHONY: dev up down models migrate seed test lint typecheck redteam redteam-live eval smoke bootstrap logs web web-e2e backup restore-drill

# Recipes that run on the host (migrate/seed/smoke) need $(DATABASE_URL) etc.
# in their own process env, not just passed to `docker compose`; `include` +
# `export` makes every `.env` var available to every recipe below.
-include .env
export

COMPOSE = docker compose -f deploy/docker-compose.dev.yml --env-file .env

dev: up models migrate seed  ## full local bring-up

up:  ## start infra + MCP servers + gateway + agents (mcp-audit/approvals/erp/comms/docs/finance/search/hrsourcing/projects, gateway, orch0, sup1, adm1, fin1, hr1, ops1, scheduler)
	$(COMPOSE) up -d

down:  ## stop and remove containers (keeps volumes)
	$(COMPOSE) down

models:  ## pull the Ollama model pool (config/models.yaml)
	bash serving/fetch_models.sh

migrate:  ## alembic upgrade head
	uv run alembic -c db/alembic.ini upgrade head

seed:  ## generate + load synthetic company data
	uv run python db/seed/generate_synthetic.py

test:  ## lint + typecheck + unit + contract tests
	uv run ruff check .
	uv run mypy -p awp_shared -p awp_mcp_base -p awp_mcp_audit -p awp_mcp_approvals -p awp_mcp_erp \
		-p awp_mcp_comms -p awp_mcp_docs -p awp_mcp_finance -p awp_mcp_search -p awp_mcp_hrsourcing \
		-p awp_mcp_projects -p awp_agent_base -p awp_agent_orch0 -p awp_agent_sup1 -p awp_agent_adm1 \
		-p awp_agent_fin1 -p awp_agent_hr1 -p awp_agent_ops1 -p awp_scheduler -p awp_gateway -p fincore \
		-p awp_evals
	uv run pytest -q

web:  ## install + run the web app dev server (needs `make up`)
	cd web && npm install && npm run dev

web-e2e:  ## Playwright ticket-flow test (mocked gateway API, no `make up` needed — see DEVIATIONS.md)
	cd web && npm install && npx playwright install --with-deps chromium && npm run test:e2e

smoke:  ## model-gateway tool-call round trip (needs `make up models`)
	uv run python serving/smoke/test_toolcall.py

redteam:  ## approval-token forgery/replay/expiry red tests (subset live in mcps/*/tests today)
	uv run pytest -q -k redteam

redteam-live:  ## behavioral red-team suite, doc 09 §4.4/§6-7 (needs `make up`; DEVIATIONS.md #23)
	uv run python -m awp_evals.harness

eval:  ## resume-extraction F1/recall live eval, doc 04 §5.1-2 (needs `make up`)
	uv run python scripts/resume_extraction_eval.py

backup:  ## nightly-style pg_dump + MinIO mirror + Qdrant snapshot (needs `make up`; DEVIATIONS.md #24)
	bash scripts/backup.sh

restore-drill:  ## restore the latest backup into a throwaway container and verify (doc 10 §6 NFR)
	bash scripts/restore_drill.sh

bootstrap:  ## one-shot: up, models, migrate, seed, smoke
	bash scripts/dev_bootstrap.sh

logs:
	$(COMPOSE) logs -f
