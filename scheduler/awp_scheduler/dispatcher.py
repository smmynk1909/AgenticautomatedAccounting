"""Dispatches due cron jobs as `TaskEnvelope`s, and sweeps open ORCH-0 DAGs
for reconciliation — doc 02 §7.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.protocols import MCPLike
from awp_agent_orch0.intent_registry import IntentRegistry
from awp_agent_orch0.reconcile import reconcile_one_dag
from awp_shared.bus import TaskBus
from awp_shared.schemas import AgentId, TaskEnvelope
from redis.asyncio import Redis

from awp_scheduler.jobs import JobSpec, is_due
from awp_scheduler.payloads import PAYLOAD_FNS

logger = structlog.get_logger(__name__)

# > one polling minute (`awp_scheduler.main.POLL_INTERVAL_S`), so a process
# restart mid-minute can't re-dispatch a job that already fired this minute.
DEDUPE_TTL_S = 150


async def dispatch_due_jobs(
    jobs: list[JobSpec],
    now: datetime,
    mcp: MCPLike,
    bus: TaskBus,
    redis: Redis,
    registry: IntentRegistry,
) -> list[str]:
    dispatched: list[str] = []
    for job in jobs:
        if not is_due(job.schedule, now):
            continue

        dedupe_key = f"sched:{job.name}:{now:%Y%m%d%H%M}"
        first = await redis.set(dedupe_key, "1", nx=True, ex=DEDUPE_TTL_S)
        if not first:
            continue

        payload = PAYLOAD_FNS[job.payload_fn](now)
        env = TaskEnvelope(
            from_agent=AgentId.SCHEDULER,
            to_agent=AgentId(job.to_agent),
            intent=job.intent,
            payload=payload,
            # doc 02 §3: never trust anything but the policy table for this —
            # a cron-triggered task gets the same treatment as an LLM-planned
            # one (e.g. `run_payroll` is gated regardless of who dispatched it).
            requires_approval=registry.requires_approval(job.intent),
        )
        await mcp.call("erp", "dispatch_task", {"envelope": env.model_dump(mode="json")})
        await bus.dispatch(env)
        dispatched.append(job.name)
        logger.info("scheduler.dispatched", job=job.name, task_id=str(env.task_id))
    return dispatched


async def reconcile_sweep(mcp: MCPLike, bus: TaskBus, checkpoints: CheckpointStore) -> list[str]:
    result = await mcp.call(
        "erp",
        "query_tasks",
        {"agent": "ORCH-0", "status": "in_progress", "top_level_only": True},
    )
    outcomes: list[str] = []
    for t in result.get("tasks", []):
        outcome = await reconcile_one_dag(mcp, bus, checkpoints, UUID(t["task_id"]))
        outcomes.append(outcome)
    return outcomes
