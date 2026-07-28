from awp_evals.schema import Outcome, RedTeamCase


def test_case_parses_minimal_fields() -> None:
    case = RedTeamCase.model_validate(
        {
            "id": "x",
            "category": "prompt_injection",
            "description": "d",
            "to_agent": "SUP-1",
            "intent": "create_ticket",
            "payload": {"channel": "chat", "category": "general", "subject": "s", "body": "b"},
        }
    )
    assert case.required == []
    assert case.forbidden == []
    assert case.timeout_s == 120.0


def test_outcome_accepts_str_and_int_values() -> None:
    assert Outcome(kind="status_is", value="done").value == "done"
    assert Outcome(kind="tool_call_count_over", value=25).value == 25
