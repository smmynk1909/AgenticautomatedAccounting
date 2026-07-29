"""ops1 process entrypoint: `python -m awp_agent_ops1.main` — a bus-worker
process. Mirrors `agents/fin1/awp_agent_fin1/main.py`'s wiring style.
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

from awp_agent_ops1.graph import build_graph

SCOPES = [
    "erp.projects.read",
    "erp.projects.write",
    "erp.people.read",
    "approvals.request",
    "approvals.read",
    "projects.write",
    "projects.read",
    "search.read",
    "comms.notify",
    "erp.dashboard.write",
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
            "projects": os.environ["MCP_PROJECTS_URL"],
            "search": os.environ["MCP_SEARCH_URL"],
            "approvals": os.environ["MCP_APPROVALS_URL"],
            "comms": os.environ["MCP_COMMS_URL"],
        },
        principal_jwt_provider=lambda: mint_service_jwt(AgentId.OPS1.value, SCOPES),
    )
    # timeout_s=180 — see agents/orch0/awp_agent_orch0/main.py's comment
    # (same CPU-inference reasoning).
    llm = LLM(
        os.environ["MODEL_GATEWAY_URL"],
        os.environ.get("MODEL_GEN", "qwen2.5:7b-instruct"),
        timeout_s=180.0,
    )
    # M-CODE gets its own, longer timeout: live-verified (Sprint 10) that a
    # *cold* model load on this host's CPU-only Ollama can take well over
    # 180s, and a client-side timeout that fires mid-load doesn't just fail
    # that attempt — Ollama aborts the in-progress load entirely, so every
    # retry restarts from scratch and 180s x 3 retries can still never
    # finish. 900s gives one attempt enough room to ride out a cold load;
    # `deploy/docker-compose.dev.yml`'s OLLAMA_KEEP_ALIVE=1h means this is
    # normally only paid once per Ollama container lifetime, not per call.
    llm_code = LLM(
        os.environ["MODEL_GATEWAY_URL"],
        os.environ.get("MODEL_CODE", "qwen2.5-coder:7b-instruct"),
        timeout_s=900.0,
    )

    async def mirror_status(env: TaskEnvelope, result: TaskResult) -> None:
        # Every other agent's on_result hook in this codebase mirrors only
        # `status`, discarding `result.summary` — harmless for flows whose
        # real output lands in a dashboard item or notification, but
        # code_assist_session's *only* output is this summary text (see
        # nodes.py's comment), and the gateway's IDE endpoint has nothing
        # else to read back via `get_task_status`. Fixed here, not in every
        # other agent's main.py — out of Sprint 10's scope, but the same
        # gap almost certainly exists there too; noted in DEVIATIONS.md.
        await mcp.call(
            "erp",
            "update_task",
            {
                "task_id": str(env.task_id),
                "status": result.status.value,
                "result": {"summary": result.summary},
            },
        )

    graph = build_graph(llm, mcp, llm_code)
    app = AgentApp(AgentId.OPS1, graph, checkpoints, graph_name="ops1", on_result=mirror_status)

    start_metrics_server()  # doc 10 HLD C19: Prometheus scrapes this agent's :9100/metrics

    await app.run_forever(bus, consumer_name=os.environ.get("HOSTNAME", "ops1-worker-1"))


if __name__ == "__main__":
    asyncio.run(_main())
