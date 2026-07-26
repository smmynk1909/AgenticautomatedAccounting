"""ORCH-0-specific graph nodes — doc 02 §3. Follows the same factory
convention as `awp_agent_base.nodes` (see that module's docstring).
"""

from __future__ import annotations

import json
from typing import Any

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_agent_base.state import AgentState
from awp_shared.bus import TaskBus
from awp_shared.errors import ValidationError
from awp_shared.schemas import AgentId, Priority, TaskEnvelope, TaskResult, TaskStatus

from awp_agent_orch0.intent_registry import IntentRegistry
from awp_agent_orch0.planner import PlanSchema
from awp_agent_orch0.validators import validate_plan

MAX_REPLAN_ATTEMPTS = 1
Node = Any


def make_classify_intent_node(llm: LLMLike, registry: IntentRegistry) -> Node:
    known = registry.known_intents()

    async def node(state: AgentState) -> AgentState:
        task = state["task"]
        # A task dispatched by intent name already (e.g. scheduler cron jobs,
        # doc 02 §7; a re-planned/resumed ORCH-0 task) carries a registered
        # intent directly — skip the LLM round trip.
        if task.intent in known:
            state["scratch"]["intent"] = task.intent
            return state

        messages = [
            {
                "role": "system",
                "content": (
                    "Classify the request into exactly one of these intents, or "
                    "'freeform' if none fit. Respond with only the intent name. "
                    "Known intents: " + ", ".join(known)
                ),
            },
            {"role": "user", "content": str(task.payload.get("text", task.intent))},
        ]
        resp = await llm.chat(messages, profile="classify")
        classified = (resp.content or "freeform").strip()
        state["scratch"]["intent"] = classified if classified in known else "freeform"
        return state

    return node


def is_known_intent(state: AgentState) -> bool:
    return state["scratch"].get("intent") != "freeform"


def make_load_playbook_node(registry: IntentRegistry) -> Node:
    async def node(state: AgentState) -> AgentState:
        intent = state["scratch"]["intent"]
        spec = registry.get(intent)
        if spec is None:
            # Freeform mapped to a name that isn't actually registered — treat
            # as unroutable rather than crashing the graph.
            state["scratch"]["intent"] = "freeform"
            state["scratch"]["freeform_mapped"] = False
            return state
        state["scratch"]["playbook"] = {
            "agent": spec.agent.value,
            "sla_hours": spec.sla_hours,
            "composite": spec.composite,
        }
        return state

    return node


def make_plan_dag_node(llm: LLMLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        task = state["task"]
        intent = state["scratch"]["intent"]
        playbook = state["scratch"].get("playbook", {})
        error_feedback = state["scratch"].get("validation_error")

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ORCH-0. Produce the smallest plan (PlanSchema JSON) of "
                    "tasks that satisfies the goal. Any task touching money, offers, "
                    "external messages, or deletion of records must set "
                    "requires_approval=true (the policy table is authoritative "
                    "regardless of what you set)."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"intent": intent, "payload": task.payload, "playbook": playbook},
                    default=str,
                ),
            },
        ]
        if error_feedback:
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous plan was invalid: {error_feedback}. Fix it.",
                }
            )

        resp = await llm.chat(messages, guided_json=PlanSchema, profile="plan")
        state["scratch"]["plan"] = json.loads(resp.content or "{}")
        return state

    return node


def make_validate_plan_node(registry: IntentRegistry) -> Node:
    async def node(state: AgentState) -> AgentState:
        plan = state["scratch"].get("plan") or {}
        try:
            validated = validate_plan(plan, registry)
        except (ValidationError, KeyError) as exc:
            attempts = state["scratch"].get("validate_attempts", 0)
            state["scratch"]["validate_attempts"] = attempts + 1
            state["scratch"]["validation_error"] = str(exc)
            return state
        state["scratch"]["validated_tasks"] = [
            {
                "id": t.id,
                "agent": t.agent,
                "intent": t.intent,
                "payload": t.payload,
                "depends_on": t.depends_on,
                "requires_approval": t.requires_approval,
                "sla_hours": t.sla_hours,
                "priority": t.priority,
            }
            for t in validated
        ]
        state["scratch"].pop("validation_error", None)
        return state

    return node


def plan_is_valid(state: AgentState) -> bool:
    return "validated_tasks" in state["scratch"]


def can_replan(state: AgentState) -> bool:
    attempts: int = state["scratch"].get("validate_attempts", 0)
    return attempts <= MAX_REPLAN_ATTEMPTS


def make_dispatch_node(mcp: MCPLike, bus: TaskBus) -> Node:
    async def node(state: AgentState) -> AgentState:
        validated: list[dict[str, Any]] = state["scratch"].get("validated_tasks") or []
        parent_task_id = state["task"].task_id
        dag: dict[str, dict[str, Any]] = {}

        for t in validated:
            ready = not t["depends_on"]
            dag[t["id"]] = {**t, "task_id": None, "status": "blocked"}
            if not ready:
                continue
            env = TaskEnvelope(
                parent_task_id=parent_task_id,
                from_agent=AgentId.ORCH0,
                to_agent=AgentId(t["agent"]),
                intent=t["intent"],
                payload=t["payload"],
                priority=Priority(t["priority"]),
                requires_approval=t["requires_approval"],
            )
            await mcp.call("erp", "dispatch_task", {"envelope": env.model_dump(mode="json")})
            await bus.dispatch(env)
            dag[t["id"]]["task_id"] = str(env.task_id)
            dag[t["id"]]["status"] = "dispatched"

        state["scratch"]["dag"] = dag
        return state

    return node


def make_freeform_triage_node(llm: LLMLike, registry: IntentRegistry) -> Node:
    known = registry.known_intents()

    async def node(state: AgentState) -> AgentState:
        task = state["task"]
        messages = [
            {
                "role": "system",
                "content": (
                    "This request didn't match a known intent. If it clearly maps to "
                    "one of these, respond with only that intent name; otherwise "
                    "respond with exactly 'ticket'. Known intents: " + ", ".join(known)
                ),
            },
            {"role": "user", "content": str(task.payload.get("text", ""))},
        ]
        resp = await llm.chat(messages, profile="classify")
        choice = (resp.content or "ticket").strip()
        if choice in known:
            state["scratch"]["intent"] = choice
            state["scratch"]["freeform_mapped"] = True
        else:
            state["scratch"]["freeform_mapped"] = False
        return state

    return node


def freeform_mapped_to_intent(state: AgentState) -> bool:
    return bool(state["scratch"].get("freeform_mapped"))


def make_create_ticket_fallback_node(mcp: MCPLike) -> Node:
    async def node(state: AgentState) -> AgentState:
        task = state["task"]
        payload = {
            "channel": "agent",
            "requester": {"type": "agent", "id": task.from_agent.value},
            "category": "cross_functional",
            "subject": f"Unrouted request: {task.intent}",
            "body": json.dumps(task.payload, default=str)[:2000],
        }
        result = await mcp.call("erp", "create_ticket", payload)
        state["scratch"]["ticket_id"] = result.get("ticket_id")
        return state

    return node


def make_respond_node(mcp: MCPLike) -> Node:
    """Builds the final `TaskResult` for *this* bus message and mirrors that
    outcome onto ORCH-0's own `orchestrator_tasks` row (whoever dispatched
    to ORCH-0 — the gateway, or the scheduler for `quarterly_review_pack` —
    is expected to have called `erp.dispatch_task` for it too, same as
    ORCH-0 does for every sub-task; a no-op `update_task` on a row that
    doesn't exist yet just 404s harmlessly server-side... note this is only
    safe because `update_task` is idempotent-cached per doc 08 §0, not
    silently swallowed). `status=IN_PROGRESS` here is what the scheduler's
    reconcile sweep (doc 02 §7) later queries for via `erp.query_tasks`.
    """

    async def node(state: AgentState) -> AgentState:
        task_id = state["task"].task_id
        dag = state["scratch"].get("dag")
        if dag:
            dispatched = [v for v in dag.values() if v["status"] == "dispatched"]
            state["result"] = TaskResult(
                task_id=task_id,
                status=TaskStatus.IN_PROGRESS,
                summary=(
                    f"dispatched {len(dispatched)}/{len(dag)} task(s), "
                    f"tracking under parent {task_id}"
                ),
            )
            await _try_update_own_status(mcp, task_id, "in_progress")
            return state

        ticket_id = state["scratch"].get("ticket_id")
        if ticket_id:
            state["result"] = TaskResult(
                task_id=task_id,
                status=TaskStatus.DONE,
                summary=f"could not route request; filed support ticket {ticket_id}",
            )
            await _try_update_own_status(mcp, task_id, "done")
            return state

        state["result"] = TaskResult(
            task_id=task_id,
            status=TaskStatus.FAILED,
            summary="orch0: no plan or ticket produced",
        )
        await _try_update_own_status(mcp, task_id, "failed")
        return state

    return node


async def _try_update_own_status(mcp: MCPLike, task_id: Any, status: str) -> None:
    try:
        await mcp.call("erp", "update_task", {"task_id": str(task_id), "status": status})
    except Exception:  # noqa: BLE001 - no row yet (no dispatcher called dispatch_task
        # for this top-level task) is an expected, harmless case, not a bug.
        pass
