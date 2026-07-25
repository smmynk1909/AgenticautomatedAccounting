"""Core cross-agent contracts — doc 11 §1.1.

Every hop in the system (task bus, MCP calls, gateway API) passes objects
built from these models. Nothing crosses a module boundary as a bare dict.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class AgentId(str, Enum):
    ORCH0 = "ORCH-0"
    ADM1 = "ADM-1"
    HR1 = "HR-1"
    OPS1 = "OPS-1"
    FIN1 = "FIN-1"
    SUP1 = "SUP-1"
    HUMAN = "HUMAN"
    SCHEDULER = "SCHEDULER"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskEnvelope(BaseModel):
    """The unit of work on the task bus (doc 00 §5, doc 11 §1.1)."""

    task_id: UUID = Field(default_factory=uuid4)
    parent_task_id: UUID | None = None
    from_agent: AgentId
    to_agent: AgentId
    intent: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: Priority = Priority.P3
    sla_deadline: datetime | None = None
    # Overwritten from the gates policy table at dispatch time — never trust
    # a value an LLM plan set here (doc 02 §3).
    requires_approval: bool = False
    trace_id: UUID = Field(default_factory=uuid4)
    idempotency_key: str = ""
    created_at: datetime = Field(default_factory=_utcnow)

    def model_post_init(self, __context: Any) -> None:
        if not self.idempotency_key:
            self.idempotency_key = str(self.task_id)


class ArtifactRef(BaseModel):
    kind: str
    uri: str | None = None
    id: str | None = None
    scope: str | None = None


ErrorCode = Literal[
    "VALIDATION",
    "NOT_FOUND",
    "PERMISSION_DENIED",
    "CONFLICT",
    "APPROVAL_REQUIRED",
    "UPSTREAM",
    "INTERNAL",
    "TIMEOUT",
]


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class TaskResult(BaseModel):
    task_id: UUID
    status: TaskStatus
    summary: str
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    error: ErrorInfo | None = None


class StepRecord(BaseModel):
    """One tool call + result inside an agent's graph run (doc 11 §2)."""

    tool: str
    server: str
    args_hash: str
    ok: bool
    result_summary: str = ""
    error: ErrorInfo | None = None
    latency_ms: float | None = None
    ts: datetime = Field(default_factory=_utcnow)
