"""fin1 process entrypoint: `python -m awp_agent_fin1.main` — a bus-worker
process. Mirrors `agents/adm1/awp_agent_adm1/main.py`'s wiring style.
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

from awp_agent_fin1.graph import build_graph

SCOPES = [
    "erp.people.read",
    "erp.policies.read",
    "finance.read",
    "finance.write",
    "finance.gated",
    "docs.render",
    "docs.read",
    "approvals.request",
    "approvals.read",
    "comms.notify",
    "erp.tasks.write",  # update_task — on_result hook's status mirror
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
            "finance": os.environ["MCP_FINANCE_URL"],
            "docs": os.environ["MCP_DOCS_URL"],
            "approvals": os.environ["MCP_APPROVALS_URL"],
            "comms": os.environ["MCP_COMMS_URL"],
        },
        principal_jwt_provider=lambda: mint_service_jwt(AgentId.FIN1.value, SCOPES),
    )
    # timeout_s=180 — see agents/orch0/awp_agent_orch0/main.py's comment
    # (same CPU-inference reasoning).
    llm = LLM(
        os.environ["MODEL_GATEWAY_URL"],
        os.environ.get("MODEL_SMALL", "qwen2.5:3b-instruct"),
        timeout_s=180.0,
    )

    async def mirror_status(env: TaskEnvelope, result: TaskResult) -> None:
        # Safety net for graph-level crashes FIN-1's own `respond` node
        # never reaches — see AgentApp.__init__'s `on_result` docstring.
        await mcp.call(
            "erp", "update_task", {"task_id": str(env.task_id), "status": result.status.value}
        )

    graph = build_graph(llm, mcp)
    app = AgentApp(AgentId.FIN1, graph, checkpoints, graph_name="fin1", on_result=mirror_status)

    start_metrics_server()  # doc 10 HLD C19: Prometheus scrapes this agent's :9100/metrics

    await app.run_forever(bus, consumer_name=os.environ.get("HOSTNAME", "fin1-worker-1"))


if __name__ == "__main__":
    asyncio.run(_main())
