from __future__ import annotations

from datetime import datetime

from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.state import new_state
from awp_agent_orch0.intent_registry import IntentRegistry
from awp_shared.bus import TaskBus
from awp_shared.schemas import AgentId, TaskEnvelope
from fakeredis.aioredis import FakeRedis

from awp_scheduler.dispatcher import dispatch_due_jobs, reconcile_sweep
from awp_scheduler.jobs import JobSpec
from awp_scheduler.tests.conftest import FakeMCP

_NOW = datetime(2026, 7, 25, 9, 0)  # a Saturday — matches only the daily job below

_DAILY_JOB = JobSpec(
    name="dashboard_refresh_daily",
    schedule={"hour": 9, "minute": 0},
    intent="dashboard_refresh",
    to_agent="ADM-1",
    payload_fn="none",
)
_PAYROLL_JOB = JobSpec(
    name="run_payroll_monthly",
    schedule={"day": 25, "hour": 9, "minute": 0},
    intent="run_payroll",
    to_agent="FIN-1",
    payload_fn="current_month",
)
_WEEKLY_JOB = JobSpec(
    name="timeline_risk_scan_weekly",
    schedule={"weekday": 0, "hour": 9, "minute": 0},  # Monday — not due on a Saturday
    intent="timeline_risk_scan",
    to_agent="OPS-1",
    payload_fn="none",
)


async def test_dispatch_due_jobs_only_dispatches_matching_jobs(
    redis: FakeRedis, bus: TaskBus, registry: IntentRegistry
) -> None:
    mcp = FakeMCP()
    dispatched = await dispatch_due_jobs(
        [_DAILY_JOB, _WEEKLY_JOB], _NOW, mcp, bus, redis, registry
    )
    assert dispatched == ["dashboard_refresh_daily"]
    dispatch_calls = [c for c in mcp.calls if c[1] == "dispatch_task"]
    assert len(dispatch_calls) == 1


async def test_dispatch_due_jobs_sets_correct_payload_and_agent(
    redis: FakeRedis, bus: TaskBus, registry: IntentRegistry
) -> None:
    mcp = FakeMCP()
    payroll_now = datetime(2026, 7, 25, 9, 0)
    await dispatch_due_jobs([_PAYROLL_JOB], payroll_now, mcp, bus, redis, registry)

    _, _, args = mcp.calls[0]
    env = TaskEnvelope.model_validate(args["envelope"])
    assert env.to_agent == AgentId.FIN1
    assert env.intent == "run_payroll"
    assert env.payload == {"month": "2026-07"}


async def test_dispatch_due_jobs_overwrites_requires_approval_from_registry(
    redis: FakeRedis, bus: TaskBus, registry: IntentRegistry
) -> None:
    mcp = FakeMCP()
    payroll_now = datetime(2026, 7, 25, 9, 0)
    await dispatch_due_jobs([_PAYROLL_JOB], payroll_now, mcp, bus, redis, registry)

    _, _, args = mcp.calls[0]
    env = TaskEnvelope.model_validate(args["envelope"])
    assert env.requires_approval is True  # payroll_run gate, non-conditional


async def test_dispatch_due_jobs_is_idempotent_within_the_same_minute(
    redis: FakeRedis, bus: TaskBus, registry: IntentRegistry
) -> None:
    mcp = FakeMCP()
    first = await dispatch_due_jobs([_DAILY_JOB], _NOW, mcp, bus, redis, registry)
    second = await dispatch_due_jobs([_DAILY_JOB], _NOW, mcp, bus, redis, registry)
    assert first == ["dashboard_refresh_daily"]
    assert second == []
    assert len([c for c in mcp.calls if c[1] == "dispatch_task"]) == 1


async def test_reconcile_sweep_calls_reconcile_for_each_open_dag(
    bus: TaskBus, checkpoints: CheckpointStore
) -> None:
    parent = TaskEnvelope(from_agent=AgentId.HUMAN, to_agent=AgentId.ORCH0, intent="run_payroll")
    state = new_state(parent)
    state["scratch"]["dag"] = {
        "t1": {
            "id": "t1",
            "agent": "FIN-1",
            "intent": "run_payroll",
            "payload": {},
            "depends_on": [],
            "requires_approval": True,
            "sla_hours": 24,
            "priority": "P3",
            "task_id": "child-1",
            "status": "dispatched",
        }
    }
    await checkpoints.save(parent.task_id, "orch0", state)

    mcp = FakeMCP(
        handlers={
            ("erp", "query_tasks"): {"tasks": [{"task_id": str(parent.task_id)}]},
            ("erp", "get_task_status"): {"task": {"status": "done", "result": {}}},
        }
    )
    outcomes = await reconcile_sweep(mcp, bus, checkpoints)

    assert outcomes == ["done"]
    query_calls = [c for c in mcp.calls if c[1] == "query_tasks"]
    assert query_calls[0][2] == {
        "agent": "ORCH-0",
        "status": "in_progress",
        "top_level_only": True,
    }


async def test_reconcile_sweep_no_open_dags_returns_empty(
    bus: TaskBus, checkpoints: CheckpointStore
) -> None:
    mcp = FakeMCP(handlers={("erp", "query_tasks"): {"tasks": []}})
    outcomes = await reconcile_sweep(mcp, bus, checkpoints)
    assert outcomes == []
