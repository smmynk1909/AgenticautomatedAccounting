"""Gate registry lookup — doc 08 §5, backed by `config/gates.yaml`."""

from __future__ import annotations

from pydantic import BaseModel

from awp_shared.config import ConfigError, get_gate


class GateConfig(BaseModel):
    name: str
    approver_roles: list[str]
    n_required: int
    ttl_h: int


def resolve_gate(gate_name: str) -> GateConfig:
    try:
        raw = get_gate(gate_name)
    except ConfigError as exc:
        from awp_shared.errors import ValidationError

        raise ValidationError(f"unknown gate: {gate_name!r}") from exc
    return GateConfig(
        name=gate_name,
        approver_roles=raw["approver_roles"],
        n_required=raw["n_required"],
        ttl_h=raw["ttl_h"],
    )
