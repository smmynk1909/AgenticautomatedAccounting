.PHONY: dev up down models migrate seed test lint typecheck redteam eval smoke bootstrap logs

COMPOSE = docker compose -f deploy/docker-compose.dev.yml --env-file .env

dev: up models migrate seed  ## full local bring-up

up:  ## start infra + MCP servers (mcp-audit, mcp-approvals, mcp-erp)
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
	uv run mypy -p awp_shared -p awp_mcp_base -p awp_mcp_audit -p awp_mcp_approvals -p awp_mcp_erp
	uv run pytest -q

smoke:  ## model-gateway tool-call round trip (needs `make up models`)
	uv run python serving/smoke/test_toolcall.py

redteam:  ## approval-token forgery/replay/expiry red tests (subset live in mcps/*/tests today)
	uv run pytest -q -k redteam

eval:  ## placeholder until evals/ lands (Sprint 7+)
	@echo "evals/ not implemented yet — see backlog Sprint 7+"

bootstrap:  ## one-shot: up, models, migrate, seed, smoke
	bash scripts/dev_bootstrap.sh

logs:
	$(COMPOSE) logs -f
