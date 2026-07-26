from __future__ import annotations

import json

from awp_shared.llm import LLMResponse
from awp_shared.schemas import Priority

from awp_agent_sup1 import intake
from awp_agent_sup1.tests.conftest import FakeLLM


async def test_classify_freeform_parses_llm_response() -> None:
    content = json.dumps(
        {
            "subcategory": "vpn",
            "priority_suggestion": "P2",
            "extracted_entities": {"asset_id": "a1"},
            "missing_info": [],
        }
    )
    llm = FakeLLM([LLMResponse(content=content)])
    result = await intake.classify_freeform(llm, "it_support", "VPN keeps dropping")
    assert result.subcategory == "vpn"
    assert result.priority_suggestion == "P2"
    assert result.extracted_entities == {"asset_id": "a1"}


def test_priority_policy_forces_p1_for_payroll_blocking() -> None:
    # doc 07 §6 acceptance test 1: "P1 policy override works when LLM
    # under-classifies a seeded payroll-blocking ticket" — LLM suggests P3.
    priority = intake.apply_priority_policy(
        "payroll", None, "We cannot run payroll for this month, it is blocked.", "P3"
    )
    assert priority == Priority.P1


def test_priority_policy_forces_p1_for_security_subcategory() -> None:
    priority = intake.apply_priority_policy("it_support", "security_incident", "", "P4")
    assert priority == Priority.P1


def test_priority_policy_uses_llm_suggestion_otherwise() -> None:
    priority = intake.apply_priority_policy("device", None, "laptop screen flickers", "P2")
    assert priority == Priority.P2


def test_priority_policy_falls_back_to_p3_on_invalid_suggestion() -> None:
    priority = intake.apply_priority_policy("device", None, "minor issue", "not-a-priority")
    assert priority == Priority.P3


def test_is_confidential_true_for_grievance() -> None:
    assert intake.is_confidential("grievance") is True


def test_is_confidential_false_for_normal_subcategory() -> None:
    assert intake.is_confidential("vpn") is False


def test_is_confidential_false_for_none() -> None:
    assert intake.is_confidential(None) is False
