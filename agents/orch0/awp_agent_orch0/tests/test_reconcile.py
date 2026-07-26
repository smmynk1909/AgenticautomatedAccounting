from __future__ import annotations

from uuid import uuid4

from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.state import new_state
from awp_shared.bus import TaskBus
from awp_shared.schemas import AgentId, TaskEnvelope

from awp_agent_orch0.reconcile import reconcile_one_dag
from awp_agent_orch0.tests.conftest import FakeMCP


def _parent_task() -> TaskEnvelope:
    return TaskEnvelope(from_agent=AgentId.HUMAN, to_agent=AgentId.ORCH0, intent="onboard_employee")


async def test_reconcile_not_found_when_no_checkpoint(
    checkpoints: CheckpointStore, bus: TaskBus
) -> None:
    outcome = await reconcile_one_dag(FakeMCP(), bus, checkpoints, uuid4())
    assert outcome == "not_found"


async def test_reconcile_dispatches_dependent_once_parent_done(
    checkpoints: CheckpointStore, bus: TaskBus
) -> None:
    parent = _parent_task()
    state = new_state(parent)
    state["scratch"]["dag"] = {
        "t1": {
            "id": "t1",
            "agent": "HR-1",
            "intent": "onboard_employee",
            "payload": {},
            "depends_on": [],
            "requires_approval": False,
            "sla_hours": 24,
            "priority": "P3",
            "task_id": "child-1",
            "status": "dispatched",
        },
        "t2": {
            "id": "t2",
            "agent": "ADM-1",
            "intent": "issue_device",
            "payload": {"emp_id": "e1", "asset_type": "laptop"},
            "depends_on": ["t1"],
            "requires_approval": False,
            "sla_hours": 24,
            "priority": "P3",
            "task_id": None,
            "status": "blocked",
        },
    }
    await checkpoints.save(parent.task_id, "orch0", state)

    mcp = FakeMCP(
        handlers={("erp", "get_task_status"): {"task": {"status": "done", "result": {}}}}
    )
    outcome = await reconcile_one_dag(mcp, bus, checkpoints, parent.task_id)

    assert outcome == "in_progress"
    saved = await checkpoints.load(parent.task_id, "orch0")
    assert saved is not None
    dag = saved["scratch"]["dag"]
    assert dag["t1"]["status"] == "done"
    assert dag["t2"]["status"] == "dispatched"
    assert dag["t2"]["task_id"] is not None


async def test_reconcile_completes_and_aggregates_when_all_terminal(
    checkpoints: CheckpointStore, bus: TaskBus
) -> None:
    parent = _parent_task()
    state = new_state(parent)
    state["scratch"]["dag"] = {
        "t1": {
            "id": "t1",
            "agent": "HR-1",
            "intent": "onboard_employee",
            "payload": {},
            "depends_on": [],
            "requires_approval": False,
            "sla_hours": 24,
            "priority": "P3",
            "task_id": "child-1",
            "status": "dispatched",
        }
    }
    await checkpoints.save(parent.task_id, "orch0", state)

    mcp = FakeMCP(
        handlers={("erp", "get_task_status"): {"task": {"status": "done", "result": {}}}}
    )
    outcome = await reconcile_one_dag(mcp, bus, checkpoints, parent.task_id)

    assert outcome == "done"
    assert [c for c in mcp.calls if c[1] == "push_dashboard_item"]
    saved = await checkpoints.load(parent.task_id, "orch0")
    assert saved is not None
    saved_result = saved["result"]
    assert saved_result is not None
    assert saved_result.status.value == "done"


async def test_reconcile_marks_failed_when_a_child_fails(
    checkpoints: CheckpointStore, bus: TaskBus
) -> None:
    parent = _parent_task()
    state = new_state(parent)
    state["scratch"]["dag"] = {
        "t1": {
            "id": "t1",
            "agent": "HR-1",
            "intent": "onboard_employee",
            "payload": {},
            "depends_on": [],
            "requires_approval": False,
            "sla_hours": 24,
            "priority": "P3",
            "task_id": "child-1",
            "status": "dispatched",
        }
    }
    await checkpoints.save(parent.task_id, "orch0", state)

    mcp = FakeMCP(
        handlers={("erp", "get_task_status"): {"task": {"status": "failed", "result": {}}}}
    )
    outcome = await reconcile_one_dag(mcp, bus, checkpoints, parent.task_id)

    assert outcome == "done"
    saved = await checkpoints.load(parent.task_id, "orch0")
    assert saved is not None
    saved_result = saved["result"]
    assert saved_result is not None
    assert saved_result.status.value == "failed"
