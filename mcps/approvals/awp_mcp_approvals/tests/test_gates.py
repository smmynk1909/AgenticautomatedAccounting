import pytest

from awp_shared.config import load_config
from awp_shared.errors import ValidationError

from awp_mcp_approvals.gates import resolve_gate


def test_resolve_gate_reads_real_config() -> None:
    """Regression guard tying this module to the real config/gates.yaml."""
    load_config.cache_clear()
    gate = resolve_gate("payroll_run")
    assert gate.approver_roles == ["finance_head", "director"]
    assert gate.n_required == 2


def test_resolve_gate_unknown_gate_raises_validation_error() -> None:
    load_config.cache_clear()
    with pytest.raises(ValidationError):
        resolve_gate("not_a_real_gate")


def test_every_gate_in_config_resolves() -> None:
    load_config.cache_clear()
    gates = load_config("gates")
    for name in gates:
        gate = resolve_gate(name)
        assert gate.n_required >= 1
        assert gate.approver_roles
