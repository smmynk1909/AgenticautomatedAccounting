from awp_shared.schemas import (
    AgentId,
    ErrorInfo,
    Priority,
    TaskEnvelope,
    TaskResult,
    TaskStatus,
)


def test_task_envelope_defaults_idempotency_key_to_task_id() -> None:
    env = TaskEnvelope(from_agent=AgentId.ORCH0, to_agent=AgentId.FIN1, intent="run_payroll")
    assert env.idempotency_key == str(env.task_id)
    assert env.priority == Priority.P3
    assert env.requires_approval is False


def test_task_envelope_round_trips_through_json() -> None:
    env = TaskEnvelope(
        from_agent=AgentId.HR1,
        to_agent=AgentId.ORCH0,
        intent="onboard_employee",
        payload={"candidate_id": "c1"},
        requires_approval=True,
    )
    raw = env.model_dump_json()
    restored = TaskEnvelope.model_validate_json(raw)
    assert restored == env


def test_task_result_carries_error_info() -> None:
    env = TaskEnvelope(from_agent=AgentId.ORCH0, to_agent=AgentId.ADM1, intent="issue_device")
    result = TaskResult(
        task_id=env.task_id,
        status=TaskStatus.FAILED,
        summary="asset out of stock",
        error=ErrorInfo(code="NOT_FOUND", message="no assets in stock", retryable=False),
    )
    assert result.error is not None
    assert result.error.code == "NOT_FOUND"
