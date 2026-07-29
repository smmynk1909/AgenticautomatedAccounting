"""Code-side plan validation — doc 02 §3: "never trust the plan blindly":
agent/intent pair must exist in the Intent Registry; `requires_approval` is
*overwritten* from the policy table; payload validated against the intent's
Pydantic model; max 12 tasks per plan; cycles rejected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from awp_shared.errors import ValidationError
from awp_shared.schemas import AgentId
from pydantic import ValidationError as PydanticValidationError

from awp_agent_orch0.intent_registry import IntentRegistry

MAX_TASKS_PER_PLAN = 12


@dataclass(frozen=True)
class ValidatedTask:
    id: str
    agent: str
    intent: str
    payload: dict[str, Any]
    depends_on: list[str]
    requires_approval: bool
    sla_hours: int
    priority: str


def validate_plan(plan: dict[str, Any], registry: IntentRegistry) -> list[ValidatedTask]:
    tasks = plan.get("tasks") or []
    if not tasks:
        raise ValidationError("plan has no tasks")
    if len(tasks) > MAX_TASKS_PER_PLAN:
        raise ValidationError(f"plan has {len(tasks)} tasks, max {MAX_TASKS_PER_PLAN}")

    ids = [t["id"] for t in tasks]
    if len(set(ids)) != len(ids):
        raise ValidationError("plan has duplicate task ids")

    validated: list[ValidatedTask] = []
    for t in tasks:
        intent = t.get("intent", "")
        spec = registry.get(intent)
        if spec is None:
            raise ValidationError(f"unknown intent in plan: {intent!r}")

        try:
            plan_agent = AgentId(t.get("agent", ""))
        except ValueError as exc:
            raise ValidationError(f"unknown agent in plan: {t.get('agent')!r}") from exc
        if plan_agent != spec.agent:
            raise ValidationError(
                f"plan routes {intent} to {plan_agent.value!r}, registry says {spec.agent.value!r}"
            )

        payload = t.get("payload", {})
        try:
            spec.payload_model.model_validate(payload)
        except PydanticValidationError as exc:
            raise ValidationError(f"task {t['id']} payload invalid for {intent}: {exc}") from exc

        depends_on = t.get("depends_on", [])
        for dep in depends_on:
            if dep not in ids:
                raise ValidationError(f"task {t['id']} depends_on unknown task {dep!r}")

        validated.append(
            ValidatedTask(
                id=t["id"],
                agent=spec.agent.value,
                intent=intent,
                payload=payload,
                depends_on=depends_on,
                requires_approval=registry.requires_approval(intent),
                sla_hours=t.get("sla_hours", spec.sla_hours),
                priority=t.get("priority", "P3"),
            )
        )

    _check_no_cycles(validated)
    return validated


def _check_no_cycles(tasks: list[ValidatedTask]) -> None:
    by_id = {t.id: t for t in tasks}
    white, gray, black = 0, 1, 2
    color = dict.fromkeys(by_id, white)

    def visit(node_id: str, stack: list[str]) -> None:
        color[node_id] = gray
        for dep in by_id[node_id].depends_on:
            if color[dep] == gray:
                raise ValidationError(
                    f"plan has a dependency cycle: {' -> '.join([*stack, node_id, dep])}"
                )
            if color[dep] == white:
                visit(dep, [*stack, node_id])
        color[node_id] = black

    for tid in by_id:
        if color[tid] == white:
            visit(tid, [])
