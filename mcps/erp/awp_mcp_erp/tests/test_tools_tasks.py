import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import NotFoundError, ValidationError
from awp_shared.schemas import AgentId, TaskEnvelope


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _dispatch_token() -> str:
    return mint_service_jwt("ORCH-0", ["erp.tasks.dispatch"])


def _write_token() -> str:
    return mint_service_jwt("FIN-1", ["erp.tasks.write"])


def _read_token() -> str:
    return mint_service_jwt("FIN-1", ["erp.tasks.read"])


def _envelope(**overrides: object) -> dict:
    defaults: dict[str, object] = dict(
        from_agent=AgentId.ORCH0,
        to_agent=AgentId.FIN1,
        intent="run_payroll",
        payload={"month": "2026-07"},
    )
    defaults.update(overrides)
    return TaskEnvelope(**defaults).model_dump(mode="json")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dispatch_task_then_get_status(erp_server: AwpMcpServer) -> None:
    env = _envelope()
    result = await erp_server.dispatch_raw(
        "dispatch_task", {"envelope": env}, _headers(_dispatch_token())
    )
    status = await erp_server.dispatch_raw(
        "get_task_status", {"task_id": result["task_id"]}, _headers(_read_token())
    )
    assert status["task"]["status"] == "pending"
    assert status["task"]["intent"] == "run_payroll"


@pytest.mark.asyncio
async def test_dispatch_task_rejects_malformed_envelope(erp_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError, match="invalid task envelope"):
        await erp_server.dispatch_raw(
            "dispatch_task",
            {"envelope": {"from_agent": "not-a-real-agent"}},
            _headers(_dispatch_token()),
        )


@pytest.mark.asyncio
async def test_claim_task_gets_oldest_pending_then_none(erp_server: AwpMcpServer) -> None:
    env = _envelope()
    await erp_server.dispatch_raw("dispatch_task", {"envelope": env}, _headers(_dispatch_token()))

    claimed = await erp_server.dispatch_raw(
        "claim_task", {"agent_id": "FIN-1"}, _headers(_write_token())
    )
    assert claimed["task"] is not None
    assert claimed["task"]["status"] == "in_progress"

    second_claim = await erp_server.dispatch_raw(
        "claim_task", {"agent_id": "FIN-1"}, _headers(_write_token())
    )
    assert second_claim["task"] is None


@pytest.mark.asyncio
async def test_update_task_sets_status_and_result(erp_server: AwpMcpServer) -> None:
    env = _envelope()
    result = await erp_server.dispatch_raw(
        "dispatch_task", {"envelope": env}, _headers(_dispatch_token())
    )
    updated = await erp_server.dispatch_raw(
        "update_task",
        {"task_id": result["task_id"], "status": "done", "result": {"summary": "ok"}},
        _headers(_write_token()),
    )
    assert updated["status"] == "done"
    assert updated["result"] == {"summary": "ok"}


@pytest.mark.asyncio
async def test_update_task_unknown_task_not_found(erp_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await erp_server.dispatch_raw(
            "update_task", {"task_id": "does-not-exist", "status": "done"}, _headers(_write_token())
        )


@pytest.mark.asyncio
async def test_get_task_status_by_parent_returns_children(erp_server: AwpMcpServer) -> None:
    parent_env = _envelope(intent="onboard_employee")
    parent_result = await erp_server.dispatch_raw(
        "dispatch_task", {"envelope": parent_env}, _headers(_dispatch_token())
    )
    child_env = _envelope(
        intent="issue_device", to_agent=AgentId.ADM1, parent_task_id=parent_result["task_id"]
    )
    await erp_server.dispatch_raw(
        "dispatch_task", {"envelope": child_env}, _headers(_dispatch_token())
    )

    status = await erp_server.dispatch_raw(
        "get_task_status", {"parent": parent_result["task_id"]}, _headers(_read_token())
    )
    assert len(status["children"]) == 1
    assert status["children"][0]["intent"] == "issue_device"
