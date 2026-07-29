"""DAG progression — advances a dispatched plan's dependent tasks and
aggregates once everything's terminal.

Doc 02 §3's pseudocode has `[monitor loop] -> [aggregate]` as graph steps
after `[dispatch]`. They're deliberately NOT modeled as `graph.py` nodes
here: `TaskEnvelope` (doc 11 §1.1) carries no `depends_on` field and
`orchestrator_tasks` (doc 09 §1) carries no DAG-edge column — a plan's
dependency graph only exists in ORCH-0's own `PlanSchema` output, so tracking
"which dependent task can now run" is bookkeeping ORCH-0 itself owns via its
checkpointed `scratch["dag"]`, not something a single bus-message handling
pass (one `AgentApp.handle` call, ack'd on return per `awp_shared.bus`) can
block on — the bus does not redeliver a successfully-returned message, so a
graph node can't "wait" across real time by returning early either.

Instead, this module's `reconcile_one_dag` is a plain async function the
**scheduler** (doc 02 §7's cron sidecar, Sprint 3) calls periodically per
open parent task: it loads ORCH-0's checkpoint directly (bypassing
`AgentApp`/the bus entirely — this isn't a new inbound `TaskEnvelope`),
advances any now-ready dependents, and aggregates + finalizes once every
child is terminal.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from awp_agent_base.checkpoint import CheckpointStore
from awp_agent_base.protocols import MCPLike
from awp_shared.bus import TaskBus
from awp_shared.schemas import AgentId, Priority, TaskEnvelope, TaskResult, TaskStatus

TERMINAL_STATUSES = {"done", "failed"}


async def reconcile_one_dag(
    mcp: MCPLike,
    bus: TaskBus,
    checkpoints: CheckpointStore,
    orch0_task_id: UUID,
) -> str:
    """Returns "not_found" | "in_progress" | "done"."""
    state = await checkpoints.load(orch0_task_id, "orch0")
    if state is None:
        return "not_found"

    dag: dict[str, dict[str, Any]] = state["scratch"].get("dag") or {}
    if not dag:
        return "not_found"

    for entry in dag.values():
        if entry["status"] == "dispatched" and entry.get("task_id"):
            status_resp = await mcp.call("erp", "get_task_status", {"task_id": entry["task_id"]})
            child = status_resp.get("task") or {}
            if child.get("status") in TERMINAL_STATUSES:
                entry["status"] = child["status"]
                entry["result"] = child.get("result")

    done_ids = {tid for tid, e in dag.items() if e["status"] in TERMINAL_STATUSES}
    for entry in dag.values():
        if entry["status"] != "blocked":
            continue
        if all(dep in done_ids for dep in entry["depends_on"]):
            env = TaskEnvelope(
                parent_task_id=orch0_task_id,
                from_agent=AgentId.ORCH0,
                to_agent=AgentId(entry["agent"]),
                intent=entry["intent"],
                payload=entry["payload"],
                priority=Priority(entry["priority"]),
                requires_approval=entry["requires_approval"],
            )
            await mcp.call("erp", "dispatch_task", {"envelope": env.model_dump(mode="json")})
            await bus.dispatch(env)
            entry["task_id"] = str(env.task_id)
            entry["status"] = "dispatched"

    if all(e["status"] in TERMINAL_STATUSES for e in dag.values()):
        failed = [e for e in dag.values() if e["status"] == "failed"]
        summary = f"DAG complete: {len(dag) - len(failed)}/{len(dag)} tasks done" + (
            f", {len(failed)} failed" if failed else ""
        )
        await mcp.call(
            "erp",
            "push_dashboard_item",
            {
                "audience_roles": ["director"],
                "panel": "orchestrator",
                "severity": "warning" if failed else "info",
                "title": "Plan complete",
                "body": summary,
                "source_task_id": str(orch0_task_id),
            },
        )
        state["result"] = TaskResult(
            task_id=orch0_task_id,
            status=TaskStatus.FAILED if failed else TaskStatus.DONE,
            summary=summary,
        )
        await checkpoints.save(orch0_task_id, "orch0", state)
        return "done"

    await checkpoints.save(orch0_task_id, "orch0", state)
    return "in_progress"
