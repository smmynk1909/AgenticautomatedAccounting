"""POST /v1/chat/completions — doc 05 §2.4's "optional editor endpoint
(OpenAI-compatible so IDE plugins like Continue work against it)".

Dispatches through the same async task-bus path as every other agent flow
(`dispatch_task` + `bus.dispatch`, doc 02 §7), then polls
`erp.get_task_status` until the `code_assist_session` task finishes —
IDE clients expect a blocking HTTP response, not a fire-and-forget task id,
so this endpoint trades the bus's normal async shape for a synchronous
wait. Streaming (`stream: true`) is not implemented — this returns the
final message in one response only; a real OpenAI-compatible streaming
implementation (SSE `data: {...}\n\n` chunks) is a reasonable follow-up,
not built here since no Sprint 10 acceptance test (doc 12 §5 cites only
05§5.3,5) requires it.

Dev-mode identity gap: `config/dev_users.yaml`'s sessions are role-based
(`dev-employee`, `dev-manager`, ...), not per-engineer, so there's no
JWT `sub` that maps to a real `emp_id` the way a Keycloak-issued token
eventually will (Sprint 11). This endpoint takes `emp_id` as an explicit
request field instead of deriving it from the session — `require_human`
still gates the endpoint to *some* authenticated session, but the ACL
check (doc 05 §5.5) is keyed off the `emp_id` field, not the session
identity. Documented in DEVIATIONS.md.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from awp_shared.auth import Principal
from awp_shared.errors import UpstreamError, ValidationError
from awp_shared.schemas import AgentId, TaskEnvelope
from fastapi import APIRouter, Depends

from awp_gateway.deps import GatewayState, get_state, require_human

router = APIRouter(prefix="/v1", tags=["codeassist"])

POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 600.0  # CPU-inference M-CODE completions can be slow — see DEVIATIONS.md #18/19


@router.post("/chat/completions")
async def chat_completions(
    payload: dict[str, Any],
    state: GatewayState = Depends(get_state),
    principal: Principal = Depends(require_human),
) -> dict[str, Any]:
    messages = payload.get("messages")
    project_id = payload.get("project_id")
    emp_id = payload.get("emp_id")
    mode = payload.get("mode", "chat")
    if not messages:
        raise ValidationError("chat_completions requires 'messages'")
    if not project_id or not emp_id:
        raise ValidationError(
            "chat_completions requires 'project_id' and 'emp_id' "
            "(dev-mode: no per-engineer session identity yet, see DEVIATIONS.md)"
        )
    user_messages = [m for m in messages if m.get("role") == "user"]
    if not user_messages:
        raise ValidationError("chat_completions requires at least one 'user' message")
    instruction = user_messages[-1]["content"]

    env = TaskEnvelope(
        from_agent=AgentId.HUMAN,
        to_agent=AgentId.OPS1,
        intent="code_assist_session",
        payload={"project_id": project_id, "mode": mode, "input": instruction, "emp_id": emp_id},
    )
    await state.mcp.call("erp", "dispatch_task", {"envelope": env.model_dump(mode="json")})
    await state.bus.dispatch(env)

    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        status = await state.mcp.call("erp", "get_task_status", {"task_id": str(env.task_id)})
        task = status["task"]
        if task["status"] == "done":
            return _to_openai_response(env, task, payload.get("model", "ops1-codeassist"))
        if task["status"] == "failed":
            raise UpstreamError(f"code_assist_session failed: {task.get('result')}")
        await asyncio.sleep(POLL_INTERVAL_S)
    raise UpstreamError(f"code_assist_session timed out after {POLL_TIMEOUT_S:.0f}s")


def _to_openai_response(env: TaskEnvelope, task: dict[str, Any], model: str) -> dict[str, Any]:
    result = task.get("result") or {}
    content = result.get("summary", "")
    return {
        "id": str(env.task_id),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
