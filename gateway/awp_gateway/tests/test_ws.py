from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import awp_gateway.ws as ws_module
from awp_gateway.tests.conftest import FakeMCP


def test_ws_stream_pushes_status_until_terminal(
    app: FastAPI, mcp: FakeMCP, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ws_module, "POLL_INTERVAL_S", 0.01)
    responses = [{"task": {"status": "in_progress"}}, {"task": {"status": "done"}}]

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        return responses.pop(0) if len(responses) > 1 else responses[0]

    mcp._handlers[("erp", "get_task_status")] = handler

    client = TestClient(app)
    with client.websocket_connect("/ws/stream?task_id=abc") as ws:
        first = ws.receive_json()
        assert first["task"]["status"] == "in_progress"
        second = ws.receive_json()
        assert second["task"]["status"] == "done"


def test_ws_stream_requires_task_id(app: FastAPI) -> None:
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/stream") as ws:
        ws.receive_json()
