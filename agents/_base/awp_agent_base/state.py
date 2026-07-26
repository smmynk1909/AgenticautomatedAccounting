"""Base LangGraph state every agent extends — doc 11 §2.

Kept a plain `TypedDict` (not a pydantic model) because that's what
`langgraph.graph.StateGraph` expects to merge node outputs into.
"""

from __future__ import annotations

from typing import Any, TypedDict

from awp_shared.schemas import StepRecord, TaskEnvelope, TaskResult

DEFAULT_TOOL_BUDGET = 25
MAX_STEPS_KEPT = 12


class AgentState(TypedDict):
    task: TaskEnvelope
    steps: list[StepRecord]
    scratch: dict[str, Any]
    result: TaskResult | None
    tool_budget: int


def new_state(task: TaskEnvelope, *, tool_budget: int = DEFAULT_TOOL_BUDGET) -> AgentState:
    return AgentState(task=task, steps=[], scratch={}, result=None, tool_budget=tool_budget)


def append_step(state: AgentState, step: StepRecord) -> None:
    """Mutates `state["steps"]` in place, trimmed to the last `MAX_STEPS_KEPT`
    (doc 11 §2: "trimmed to last 12") so long-running plans don't blow the
    prompt budget on replan/summarize calls."""
    state["steps"].append(step)
    if len(state["steps"]) > MAX_STEPS_KEPT:
        del state["steps"][: len(state["steps"]) - MAX_STEPS_KEPT]
