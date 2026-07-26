"""`PlanSchema` — the guided-JSON contract ORCH-0's planner LLM call is
constrained to (doc 02 §3). Never trusted as-is: `validators.validate_plan`
re-derives `agent`/`requires_approval` from the Intent Registry and
`config/gates.yaml` before anything is dispatched.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlanTask(BaseModel):
    id: str
    agent: str
    intent: str
    payload: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    sla_hours: int = 24
    priority: str = "P3"


class PlanSchema(BaseModel):
    goal: str
    tasks: list[PlanTask]
    success_criteria: str = ""
    report_to: list[str] = Field(default_factory=lambda: ["requester"])
