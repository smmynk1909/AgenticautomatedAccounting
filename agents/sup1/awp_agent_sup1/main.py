"""sup1 process entrypoint: `python -m awp_agent_sup1.main` — a bus-worker
process. Mirrors `agents/orch0/awp_agent_orch0/main.py`'s wiring style.
"""

from __future__ import annotations

import asyncio
import os

from awp_agent_base.app import AgentApp
from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.metrics_server import start_metrics_server
from awp_mcp_base.uow import UnitOfWork, make_engine
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import TaskBus, make_redis
from awp_shared.config import validate_all
from awp_shared.llm import LLM
from awp_shared.mcpc import MCP
from awp_shared.schemas import AgentId, TaskEnvelope, TaskResult

from awp_agent_sup1.graph import build_graph

SCOPES = [
    "erp.tickets.read",
    "erp.tickets.write",
    "erp.tickets.write.summary",
    "erp.tasks.write",  # update_task — on_result hook's status mirror
    "erp.dashboard.write",
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
        {"erp": os.environ["MCP_ERP_URL"]},
        principal_jwt_provider=lambda: mint_service_jwt(AgentId.SUP1.value, SCOPES),
    )
    # timeout_s=180 — see agents/orch0/awp_agent_orch0/main.py's comment
    # (same CPU-inference reasoning; M-SMALL is faster but not instant).
    llm = LLM(
        os.environ["MODEL_GATEWAY_URL"],
        os.environ.get("MODEL_SMALL", "qwen2.5:3b-instruct"),
        timeout_s=180.0,
    )

    async def mirror_status(env: TaskEnvelope, result: TaskResult) -> None:
        # Safety net for graph-level crashes SUP-1's own `respond` node never
        # reaches — see AgentApp.__init__'s `on_result` docstring and
        # agents/orch0/awp_agent_orch0/main.py's identical wiring. Also the
        # *only* path that ever persists `result.summary` — see the same
        # note in agents/hr1/awp_agent_hr1/main.py.
        await mcp.call(
            "erp",
            "update_task",
            {
                "task_id": str(env.task_id),
                "status": result.status.value,
                "result": {"summary": result.summary},
            },
        )

    graph = build_graph(llm, mcp)
    app = AgentApp(AgentId.SUP1, graph, checkpoints, graph_name="sup1", on_result=mirror_status)

    start_metrics_server()  # doc 10 HLD C19: Prometheus scrapes this agent's :9100/metrics

    await app.run_forever(bus, consumer_name=os.environ.get("HOSTNAME", "sup1-worker-1"))


if __name__ == "__main__":
    asyncio.run(_main())
