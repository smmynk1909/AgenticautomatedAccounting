from __future__ import annotations

from typing import Any

import pytest
from awp_shared.errors import ValidationError

from awp_agent_orch0.intent_registry import IntentRegistry
from awp_agent_orch0.validators import MAX_TASKS_PER_PLAN, validate_plan


@pytest.fixture(scope="module")
def registry() -> IntentRegistry:
    return IntentRegistry()


def _plan(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"goal": "test", "tasks": tasks}


def test_valid_single_task_plan(registry: IntentRegistry) -> None:
    plan = _plan(
        [
            {
                "id": "t1",
                "agent": "ADM-1",
                "intent": "return_device",
                "payload": {"asset_id": "a1", "emp_id": "e1"},
                "depends_on": [],
            }
        ]
    )
    validated = validate_plan(plan, registry)
    assert len(validated) == 1
    assert validated[0].requires_approval is False


def test_unknown_intent_raises(registry: IntentRegistry) -> None:
    plan = _plan([{"id": "t1", "agent": "ADM-1", "intent": "not_a_real_intent", "payload": {}}])
    with pytest.raises(ValidationError, match="unknown intent"):
        validate_plan(plan, registry)


def test_unknown_agent_raises(registry: IntentRegistry) -> None:
    plan = _plan([{"id": "t1", "agent": "NOT-AN-AGENT", "intent": "return_device", "payload": {}}])
    with pytest.raises(ValidationError, match="unknown agent"):
        validate_plan(plan, registry)


def test_agent_mismatch_raises(registry: IntentRegistry) -> None:
    plan = _plan(
        [
            {
                "id": "t1",
                "agent": "FIN-1",  # registry says ADM-1 owns return_device
                "intent": "return_device",
                "payload": {"asset_id": "a1", "emp_id": "e1"},
            }
        ]
    )
    with pytest.raises(ValidationError, match="registry says"):
        validate_plan(plan, registry)


def test_invalid_payload_raises(registry: IntentRegistry) -> None:
    plan = _plan(
        [{"id": "t1", "agent": "ADM-1", "intent": "return_device", "payload": {"bogus": True}}]
    )
    with pytest.raises(ValidationError, match="payload invalid"):
        validate_plan(plan, registry)


def test_too_many_tasks_raises(registry: IntentRegistry) -> None:
    tasks = [
        {
            "id": f"t{i}",
            "agent": "ADM-1",
            "intent": "return_device",
            "payload": {"asset_id": "a1", "emp_id": "e1"},
        }
        for i in range(MAX_TASKS_PER_PLAN + 1)
    ]
    with pytest.raises(ValidationError, match="max"):
        validate_plan(_plan(tasks), registry)


def test_duplicate_ids_raises(registry: IntentRegistry) -> None:
    task = {
        "id": "t1",
        "agent": "ADM-1",
        "intent": "return_device",
        "payload": {"asset_id": "a1", "emp_id": "e1"},
    }
    with pytest.raises(ValidationError, match="duplicate"):
        validate_plan(_plan([task, dict(task)]), registry)


def test_unknown_dependency_raises(registry: IntentRegistry) -> None:
    plan = _plan(
        [
            {
                "id": "t1",
                "agent": "ADM-1",
                "intent": "return_device",
                "payload": {"asset_id": "a1", "emp_id": "e1"},
                "depends_on": ["ghost"],
            }
        ]
    )
    with pytest.raises(ValidationError, match="depends_on unknown"):
        validate_plan(plan, registry)


def test_cycle_raises(registry: IntentRegistry) -> None:
    plan = _plan(
        [
            {
                "id": "t1",
                "agent": "ADM-1",
                "intent": "return_device",
                "payload": {"asset_id": "a1", "emp_id": "e1"},
                "depends_on": ["t2"],
            },
            {
                "id": "t2",
                "agent": "ADM-1",
                "intent": "return_device",
                "payload": {"asset_id": "a1", "emp_id": "e1"},
                "depends_on": ["t1"],
            },
        ]
    )
    with pytest.raises(ValidationError, match="cycle"):
        validate_plan(plan, registry)


def test_requires_approval_cannot_be_lowered_by_plan(registry: IntentRegistry) -> None:
    """doc 02 §3: "requires_approval is *overwritten* from the policy table
    (LLM cannot lower it)". Simulates a prompt-injected/malicious plan that
    explicitly claims requires_approval=False for a gated, non-conditional
    intent (doc 02 §9 acceptance test 3)."""
    plan = _plan(
        [
            {
                "id": "t1",
                "agent": "FIN-1",
                "intent": "run_payroll",
                "payload": {"month": "2026-07"},
                "requires_approval": False,  # the plan's own (untrusted) claim
            }
        ]
    )
    validated = validate_plan(plan, registry)
    assert validated[0].requires_approval is True
