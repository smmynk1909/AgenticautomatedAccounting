"""POST /api/chat/{agent_id} — doc 11 §5: dispatch to bus. `agent_id`
resolves to a registered `AgentId` (usually `ORCH-0`; other agents aren't
built yet — Sprint 4+ — but the route itself is agent-agnostic per the doc).
"""

from __future__ import annotations

from typing import Any

from awp_shared.auth import Principal
from awp_shared.errors import ValidationError
from awp_shared.schemas import AgentId, TaskEnvelope
from fastapi import APIRouter, Depends

from awp_gateway.deps import GatewayState, get_state, require_human

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/{agent_id}")
async def chat(
    agent_id: str,
    payload: dict[str, Any],
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, str]:
    message = payload.get("message")
    if not message:
        raise ValidationError("chat requires 'message'")
    try:
        to_agent = AgentId(agent_id)
    except ValueError as exc:
        raise ValidationError(f"unknown agent: {agent_id!r}") from exc

    env = TaskEnvelope(
        from_agent=AgentId.HUMAN,
        to_agent=to_agent,
        intent="freeform",
        payload={
            "text": message,
            "requester_id": principal.sub,
            "context_refs": payload.get("context_refs", []),
        },
    )
    await state.mcp.call("erp", "dispatch_task", {"envelope": env.model_dump(mode="json")})
    await state.bus.dispatch(env)
    return {"task_id": str(env.task_id)}
