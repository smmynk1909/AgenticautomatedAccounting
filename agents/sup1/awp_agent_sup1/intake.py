"""SUP-1a Intake — doc 07 §3.1. Priority is code, not LLM: "Priority policy
is code: P1 = production-client impact / payroll blocking / security; LLM
only suggests, policy table decides." Confidential-subcategory routing
itself is enforced by `mcp-erp.create_ticket` (doc 07 §3.1's fast-path),
not duplicated here — `is_confidential` below is only used to skip the LLM
classification step for those tickets ("minimal processing").
"""

from __future__ import annotations

import json
from typing import Any

from awp_agent_base.protocols import LLMLike
from awp_shared.config import load_config
from awp_shared.schemas import Priority
from pydantic import BaseModel, Field

# doc 07 §3.1: "P1 = production-client impact / payroll blocking / security."
_PAYROLL_BLOCKING_KEYWORDS = (
    "payroll blocking",
    "cannot run payroll",
    "can't run payroll",
    "payroll is blocked",
    "salary not processed",
)
_SECURITY_KEYWORDS = ("security breach", "data leak", "unauthorized access", "security incident")


class IntakeClassification(BaseModel):
    subcategory: str | None = None
    priority_suggestion: str = "P3"
    extracted_entities: dict[str, Any] = Field(default_factory=dict)
    missing_info: list[str] = Field(default_factory=list)


async def classify_freeform(llm: LLMLike, category: str, body: str) -> IntakeClassification:
    messages = [
        {
            "role": "system",
            "content": (
                "Classify this support ticket. Output ONLY the requested JSON "
                "schema (subcategory, priority_suggestion, extracted_entities, "
                "missing_info)."
            ),
        },
        {"role": "user", "content": json.dumps({"category": category, "body": body})},
    ]
    resp = await llm.chat(messages, guided_json=IntakeClassification, profile="extract")
    return IntakeClassification.model_validate_json(resp.content or "{}")


def apply_priority_policy(
    category: str, subcategory: str | None, body: str, llm_priority: str
) -> Priority:
    text = f"{subcategory or ''} {body}".lower()
    if category == "payroll" and any(kw in text for kw in _PAYROLL_BLOCKING_KEYWORDS):
        return Priority.P1
    if subcategory == "security_incident" or any(kw in text for kw in _SECURITY_KEYWORDS):
        return Priority.P1
    try:
        return Priority(llm_priority)
    except ValueError:
        return Priority.P3


def is_confidential(subcategory: str | None) -> bool:
    confidential_subcats: list[str] = load_config("routing").get("confidential_subcategories", [])
    return bool(subcategory) and subcategory in confidential_subcats
