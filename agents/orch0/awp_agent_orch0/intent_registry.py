"""Loads `config/intents.yaml` and resolves each entry's payload model — doc
02 §5 / doc 11 §8.
"""

from __future__ import annotations

from dataclasses import dataclass

from awp_shared.config import load_config
from awp_shared.intent_models import get_payload_model
from awp_shared.schemas import AgentId
from pydantic import BaseModel


@dataclass(frozen=True)
class IntentSpec:
    intent: str
    agent: AgentId
    payload_model: type[BaseModel]
    gate: str | None
    conditional: bool
    sla_hours: int
    composite: bool


class IntentRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, IntentSpec] = {}
        for entry in load_config("intents"):
            self._specs[entry["intent"]] = IntentSpec(
                intent=entry["intent"],
                agent=AgentId(entry["agent"]),
                payload_model=get_payload_model(entry["intent"]),
                gate=entry.get("gate"),
                conditional=bool(entry.get("conditional", False)),
                sla_hours=int(entry["sla_hours"]),
                composite=bool(entry.get("composite", False)),
            )

    def get(self, intent: str) -> IntentSpec | None:
        return self._specs.get(intent)

    def known_intents(self) -> list[str]:
        return sorted(self._specs)

    def requires_approval(self, intent: str) -> bool:
        """doc 02 §3: `requires_approval` is *overwritten* from the policy
        table — an LLM plan can never lower it. A `conditional` gate (doc
        02/gates.yaml comment) is left `False` here: the per-instance
        decision for those is made by the owning agent's own deterministic
        policy node at execution time, not by ORCH-0's plan validation."""
        spec = self._specs.get(intent)
        if spec is None or spec.gate is None:
            return False
        return not spec.conditional
