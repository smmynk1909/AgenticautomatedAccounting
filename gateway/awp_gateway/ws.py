"""WS `/ws/stream?task_id=` — doc 11 §5's `WS /ws/stream?trace_id=`
simplified to poll-based `task_id` status pushes (see below for why).
"""

from __future__ import annotations

import asyncio

from awp_shared.errors import AwpError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from awp_gateway.deps import GatewayState

router = APIRouter()

POLL_INTERVAL_S = 1.0
TERMINAL_STATUSES = {"done", "failed"}


@router.websocket("/ws/stream")
async def stream(websocket: WebSocket) -> None:
    """Polls `erp.get_task_status` for `task_id` (query param) and pushes
    the current status as a JSON frame every second until it reaches a
    terminal status, then closes.

    Doc 11 §5 specifies pushing individual `StepRecord`s per tool call and
    keying by `trace_id`. Neither exists yet: no agent publishes a per-step
    event anywhere — that needs a Redis pub/sub channel `AgentApp` writes to
    after each node, worth adding once a second agent lands and there's
    real multi-step work to watch live — and `get_task_status` has no
    trace_id lookup either (only `task_id`/`parent`). So this polls the same
    durable `orchestrator_tasks` status every client already gets from
    `GET /api/tasks/{task_id}`, just pushed instead of pulled.
    """
    await websocket.accept()
    task_id = websocket.query_params.get("task_id")
    if not task_id:
        await websocket.close(code=4400, reason="task_id query param required")
        return

    state: GatewayState = websocket.app.state.gateway
    try:
        while True:
            try:
                result = await state.mcp.call("erp", "get_task_status", {"task_id": task_id})
            except AwpError as exc:
                await websocket.send_json({"error": exc.message})
                break
            await websocket.send_json(result)
            if result.get("task", {}).get("status") in TERMINAL_STATUSES:
                break
            await asyncio.sleep(POLL_INTERVAL_S)
    except WebSocketDisconnect:
        return
    await websocket.close()
