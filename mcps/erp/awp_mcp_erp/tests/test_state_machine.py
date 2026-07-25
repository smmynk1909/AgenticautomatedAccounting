import pytest
from awp_shared.errors import ValidationError

from awp_mcp_erp.state_machine import validate_transition


def test_legal_transition_does_not_raise() -> None:
    validate_transition("new", "triaged")
    validate_transition("triaged", "assigned")
    validate_transition("resolved", "closed")


def test_same_state_is_a_no_op() -> None:
    validate_transition("in_progress", "in_progress")


def test_illegal_transition_raises() -> None:
    with pytest.raises(ValidationError, match="illegal ticket transition"):
        validate_transition("new", "closed")


def test_closed_can_only_reopen() -> None:
    with pytest.raises(ValidationError):
        validate_transition("closed", "in_progress")
    validate_transition("closed", "reopened")


def test_unknown_current_state_has_no_allowed_transitions() -> None:
    with pytest.raises(ValidationError):
        validate_transition("some_unknown_state", "triaged")
