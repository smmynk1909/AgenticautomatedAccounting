from __future__ import annotations

from awp_shared.schemas import AgentId

from awp_agent_orch0.intent_registry import IntentRegistry


def test_loads_every_intents_yaml_entry() -> None:
    registry = IntentRegistry()
    assert "run_payroll" in registry.known_intents()
    assert "onboard_employee" in registry.known_intents()
    assert len(registry.known_intents()) >= 28


def test_get_unknown_intent_returns_none() -> None:
    registry = IntentRegistry()
    assert registry.get("does_not_exist") is None


def test_spec_resolves_payload_model_and_agent() -> None:
    registry = IntentRegistry()
    spec = registry.get("run_payroll")
    assert spec is not None
    assert spec.agent == AgentId.FIN1
    assert spec.gate == "payroll_run"
    assert spec.conditional is False


def test_requires_approval_true_for_non_conditional_gate() -> None:
    registry = IntentRegistry()
    assert registry.requires_approval("run_payroll") is True


def test_requires_approval_false_for_null_gate() -> None:
    registry = IntentRegistry()
    assert registry.requires_approval("return_device") is False


def test_requires_approval_false_for_conditional_gate() -> None:
    # doc 02 §3 / intents.yaml comment: conditional gates are decided by the
    # owning agent's own policy node, not by ORCH-0's plan validation.
    registry = IntentRegistry()
    assert registry.requires_approval("issue_device") is False


def test_requires_approval_false_for_unknown_intent() -> None:
    registry = IntentRegistry()
    assert registry.requires_approval("does_not_exist") is False
