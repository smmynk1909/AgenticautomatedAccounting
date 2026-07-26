from __future__ import annotations

import json

from awp_agent_base.state import new_state
from awp_shared.bus import TaskBus
from awp_shared.llm import LLMResponse
from awp_shared.schemas import AgentId, TaskEnvelope, TaskStatus

from awp_agent_orch0 import nodes
from awp_agent_orch0.intent_registry import IntentRegistry
from awp_agent_orch0.tests.conftest import FakeLLM, FakeMCP


def _task(intent: str = "freeform", payload: dict | None = None) -> TaskEnvelope:
    return TaskEnvelope(
        from_agent=AgentId.HUMAN, to_agent=AgentId.ORCH0, intent=intent, payload=payload or {}
    )


async def test_classify_intent_skips_llm_for_already_known_intent(
    registry: IntentRegistry,
) -> None:
    llm = FakeLLM([])
    state = new_state(_task(intent="run_payroll"))
    node = nodes.make_classify_intent_node(llm, registry)
    result = await node(state)
    assert result["scratch"]["intent"] == "run_payroll"
    assert llm.calls == []


async def test_classify_intent_llm_maps_to_known_intent(registry: IntentRegistry) -> None:
    llm = FakeLLM([LLMResponse(content="run_payroll")])
    state = new_state(_task(intent="freeform", payload={"text": "please run payroll"}))
    node = nodes.make_classify_intent_node(llm, registry)
    result = await node(state)
    assert result["scratch"]["intent"] == "run_payroll"


async def test_classify_intent_llm_unmapped_falls_back_freeform(registry: IntentRegistry) -> None:
    llm = FakeLLM([LLMResponse(content="book flight tickets")])
    state = new_state(_task(intent="freeform", payload={"text": "book me a flight"}))
    node = nodes.make_classify_intent_node(llm, registry)
    result = await node(state)
    assert result["scratch"]["intent"] == "freeform"


def test_is_known_intent() -> None:
    state = new_state(_task())
    state["scratch"]["intent"] = "freeform"
    assert nodes.is_known_intent(state) is False
    state["scratch"]["intent"] = "run_payroll"
    assert nodes.is_known_intent(state) is True


async def test_load_playbook_sets_playbook(registry: IntentRegistry) -> None:
    state = new_state(_task())
    state["scratch"]["intent"] = "run_payroll"
    node = nodes.make_load_playbook_node(registry)
    result = await node(state)
    assert result["scratch"]["playbook"]["agent"] == "FIN-1"


async def test_plan_dag_stores_parsed_plan(registry: IntentRegistry) -> None:
    plan_json = json.dumps(
        {"goal": "g", "tasks": [{"id": "t1", "agent": "FIN-1", "intent": "run_payroll"}]}
    )
    llm = FakeLLM([LLMResponse(content=plan_json)])
    state = new_state(_task())
    state["scratch"]["intent"] = "run_payroll"
    node = nodes.make_plan_dag_node(llm)
    result = await node(state)
    assert result["scratch"]["plan"]["tasks"][0]["id"] == "t1"


async def test_validate_plan_success(registry: IntentRegistry) -> None:
    state = new_state(_task())
    state["scratch"]["plan"] = {
        "goal": "g",
        "tasks": [
            {
                "id": "t1",
                "agent": "FIN-1",
                "intent": "run_payroll",
                "payload": {"month": "2026-07"},
            }
        ],
    }
    node = nodes.make_validate_plan_node(registry)
    result = await node(state)
    assert nodes.plan_is_valid(result)
    assert result["scratch"]["validated_tasks"][0]["requires_approval"] is True


async def test_validate_plan_failure_increments_attempts(registry: IntentRegistry) -> None:
    state = new_state(_task())
    state["scratch"]["plan"] = {"goal": "g", "tasks": []}
    node = nodes.make_validate_plan_node(registry)
    result = await node(state)
    assert not nodes.plan_is_valid(result)
    assert result["scratch"]["validate_attempts"] == 1
    assert nodes.can_replan(result) is True

    result2 = await node(result)
    assert result2["scratch"]["validate_attempts"] == 2
    assert nodes.can_replan(result2) is False


async def test_dispatch_dispatches_ready_tasks_and_blocks_dependents(bus: TaskBus) -> None:
    mcp = FakeMCP()
    state = new_state(_task())
    state["scratch"]["validated_tasks"] = [
        {
            "id": "t1",
            "agent": "FIN-1",
            "intent": "run_payroll",
            "payload": {"month": "2026-07"},
            "depends_on": [],
            "requires_approval": True,
            "sla_hours": 24,
            "priority": "P2",
        },
        {
            "id": "t2",
            "agent": "FIN-1",
            "intent": "generate_salary_slips",
            "payload": {"month": "2026-07"},
            "depends_on": ["t1"],
            "requires_approval": True,
            "sla_hours": 24,
            "priority": "P2",
        },
    ]
    node = nodes.make_dispatch_node(mcp, bus)
    result = await node(state)

    dag = result["scratch"]["dag"]
    assert dag["t1"]["status"] == "dispatched"
    assert dag["t1"]["task_id"] is not None
    assert dag["t2"]["status"] == "blocked"
    assert dag["t2"]["task_id"] is None
    dispatch_calls = [c for c in mcp.calls if c[1] == "dispatch_task"]
    assert len(dispatch_calls) == 1


async def test_freeform_triage_maps_to_known_intent(registry: IntentRegistry) -> None:
    llm = FakeLLM([LLMResponse(content="create_ticket")])
    state = new_state(_task(payload={"text": "my laptop is broken, please log it"}))
    node = nodes.make_freeform_triage_node(llm, registry)
    result = await node(state)
    assert nodes.freeform_mapped_to_intent(result) is True
    assert result["scratch"]["intent"] == "create_ticket"


async def test_freeform_triage_unmapped(registry: IntentRegistry) -> None:
    llm = FakeLLM([LLMResponse(content="ticket")])
    state = new_state(_task(payload={"text": "book me a flight to Goa"}))
    node = nodes.make_freeform_triage_node(llm, registry)
    result = await node(state)
    assert nodes.freeform_mapped_to_intent(result) is False


async def test_create_ticket_fallback_calls_mcp_and_stores_id() -> None:
    mcp = FakeMCP(handlers={("erp", "create_ticket"): {"ticket_id": "TKT-2026-0001"}})
    state = new_state(_task(intent="freeform", payload={"text": "book a flight"}))
    node = nodes.make_create_ticket_fallback_node(mcp)
    result = await node(state)
    assert result["scratch"]["ticket_id"] == "TKT-2026-0001"
    assert mcp.calls[0][:2] == ("erp", "create_ticket")


async def test_respond_in_progress_when_dag_dispatched() -> None:
    mcp = FakeMCP()
    state = new_state(_task())
    state["scratch"]["dag"] = {"t1": {"status": "dispatched", "task_id": "abc"}}
    result = await nodes.make_respond_node(mcp)(state)
    assert result["result"] is not None
    assert result["result"].status == TaskStatus.IN_PROGRESS
    assert mcp.calls[0] == (
        "erp",
        "update_task",
        {"task_id": str(state["task"].task_id), "status": "in_progress"},
    )


async def test_respond_done_when_ticket_created() -> None:
    mcp = FakeMCP()
    state = new_state(_task())
    state["scratch"]["ticket_id"] = "TKT-1"
    result = await nodes.make_respond_node(mcp)(state)
    assert result["result"] is not None
    assert result["result"].status == TaskStatus.DONE


async def test_respond_failed_when_nothing_produced() -> None:
    mcp = FakeMCP()
    state = new_state(_task())
    result = await nodes.make_respond_node(mcp)(state)
    assert result["result"] is not None
    assert result["result"].status == TaskStatus.FAILED


async def test_respond_swallows_update_task_failure_when_no_row_exists() -> None:
    class _RaisingMCP(FakeMCP):
        async def call(self, server: str, tool: str, args: dict) -> dict:
            raise RuntimeError("no such task")

    state = new_state(_task())
    state["scratch"]["ticket_id"] = "TKT-1"
    result = await nodes.make_respond_node(_RaisingMCP())(state)
    assert result["result"] is not None
    assert result["result"].status == TaskStatus.DONE
