"""scheduler process entrypoint: `python -m awp_scheduler.main`. Polls once a
minute — good enough for the daily/weekly/monthly/quarterly cadences in
`jobs.yaml`; not wall-clock-precise cron (`jobs.is_due` compares against the
poll's own `now`, so a slow tick just delays a job up to ~60s, never skips
it, as long as the process keeps running).
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import structlog
from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.metrics_server import start_metrics_server
from awp_agent_orch0.intent_registry import IntentRegistry
from awp_mcp_base.uow import UnitOfWork, make_engine
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import TaskBus, make_redis
from awp_shared.config import validate_all
from awp_shared.mcpc import MCP
from awp_shared.schemas import AgentId
from redis.asyncio import Redis

from awp_scheduler.auditcheck import verify_audit_chain_daily
from awp_scheduler.dispatcher import dispatch_due_jobs, reconcile_sweep
from awp_scheduler.jobs import JobSpec, load_jobs

logger = structlog.get_logger(__name__)

POLL_INTERVAL_S = 60
AUDIT_VERIFY_DEDUPE_TTL_S = 25 * 3600  # > 1 day, so a mid-day restart can't re-fire today's check

SCOPES = [
    "erp.tasks.dispatch",
    "erp.tasks.read",
    "erp.tasks.write",
    "erp.dashboard.write",
    "audit.admin",
    "comms.notify",
]


async def _tick(
    mcp: MCP,
    bus: TaskBus,
    redis: Redis,
    registry: IntentRegistry,
    checkpoints: CheckpointStore,
    jobs: list[JobSpec],
) -> None:
    now = datetime.now(UTC)
    await dispatch_due_jobs(jobs, now, mcp, bus, redis, registry)
    await reconcile_sweep(mcp, bus, checkpoints)

    dedupe_key = f"sched:audit_verify:{now:%Y%m%d}"
    if await redis.set(dedupe_key, "1", nx=True, ex=AUDIT_VERIFY_DEDUPE_TTL_S):
        await verify_audit_chain_daily(mcp, now.date())


async def _main() -> None:
    validate_all()
    jobs = load_jobs()
    registry = IntentRegistry()

    engine = make_engine(os.environ["DATABASE_URL"])
    checkpoints = CheckpointStore(UnitOfWork(engine), dialect="postgresql")

    redis = make_redis(os.environ["REDIS_URL"])
    bus = TaskBus(redis)

    mcp = MCP(
        {
            "erp": os.environ["MCP_ERP_URL"],
            "audit": os.environ["MCP_AUDIT_URL"],
            "comms": os.environ["MCP_COMMS_URL"],
        },
        principal_jwt_provider=lambda: mint_service_jwt(AgentId.SCHEDULER.value, SCOPES),
    )

    start_metrics_server()  # doc 10 HLD C19: Prometheus scrapes this at :9100/metrics

    while True:
        try:
            await _tick(mcp, bus, redis, registry, checkpoints, jobs)
        except Exception as exc:  # noqa: BLE001 - a transient dependency
            # outage (mcp-erp mid-restart, Redis blip) must not kill this
            # long-running process — the next tick, 60s later, just retries.
            # Reproduced (Sprint 3): a rolling `docker compose up --build`
            # crash-looped the scheduler container on `erp.query_tasks`
            # connection refused while mcp-erp itself was restarting.
            logger.error("scheduler.tick_failed", error=str(exc))
        await asyncio.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    asyncio.run(_main())
