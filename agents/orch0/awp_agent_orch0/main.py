"""orch0 process entrypoint: `python -m awp_agent_orch0.main` — a bus-worker
process (no HTTP surface of its own; the gateway dispatches to it over Redis
Streams, doc 11 §5). Mirrors `mcps/erp/awp_mcp_erp/main.py`'s wiring style.
"""

from __future__ import annotations

import asyncio
import os

from awp_agent_base.app import AgentApp
from awp_agent_base.checkpoint import CheckpointStore
from awp_mcp_base.uow import UnitOfWork, make_engine
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import TaskBus, make_redis
from awp_shared.config import validate_all
from awp_shared.llm import LLM
from awp_shared.mcpc import MCP
from awp_shared.schemas import AgentId, TaskEnvelope, TaskResult

from awp_agent_orch0.graph import build_graph
from awp_agent_orch0.intent_registry import IntentRegistry

SCOPES = [
    "erp.tasks.dispatch",
    "erp.tasks.read",
    "erp.tasks.write",  # update_task — respond node's status mirror + on_result hook
    "erp.tickets.write",
    "erp.dashboard.write",
    "approvals.request",
    "approvals.read",
    "audit.write",
]


async def _main() -> None:
    validate_all()

    engine = make_engine(os.environ["DATABASE_URL"])
    uow = UnitOfWork(engine)
    checkpoints = CheckpointStore(uow, dialect="postgresql")

    redis = make_redis(os.environ["REDIS_URL"])
    bus = TaskBus(redis)

    mcp = MCP(
        {
            "erp": os.environ["MCP_ERP_URL"],
            "approvals": os.environ["MCP_APPROVALS_URL"],
            "audit": os.environ["MCP_AUDIT_URL"],
        },
        principal_jwt_provider=lambda: mint_service_jwt(AgentId.ORCH0.value, SCOPES),
    )
    # timeout_s=180, not LLM's 60s default: CPU-only inference (DEVIATIONS.md
    # #1, no GPU on this dev box) measured ~30-35s for a single classify/plan
    # call with ORCH-0's full prompt (intent list + system text) — the 60s
    # default triggered a spurious retry on the very first real request.
    llm = LLM(
        os.environ["MODEL_GATEWAY_URL"],
        os.environ.get("MODEL_GEN", "qwen2.5:7b-instruct"),
        timeout_s=180.0,
    )

    async def mirror_status(env: TaskEnvelope, result: TaskResult) -> None:
        # Safety net for paths `graph.py`'s own `respond` node never reaches
        # (a graph-level crash, e.g. all LLM retries exhausted) — see
        # `AgentApp.__init__`'s `on_result` docstring. Harmless if `respond`
        # already set the same status (plain idempotent UPDATE).
        await mcp.call(
            "erp", "update_task", {"task_id": str(env.task_id), "status": result.status.value}
        )

    registry = IntentRegistry()
    graph = build_graph(llm, mcp, bus, registry)
    app = AgentApp(AgentId.ORCH0, graph, checkpoints, graph_name="orch0", on_result=mirror_status)

    await app.run_forever(bus, consumer_name=os.environ.get("HOSTNAME", "orch0-worker-1"))


if __name__ == "__main__":
    asyncio.run(_main())
