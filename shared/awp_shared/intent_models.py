"""Payload models for every entry in `config/intents.yaml` — doc 11 §8.

ORCH-0 (Sprint 3) validates a dispatched `TaskEnvelope.payload` against the
model named by the intent's `payload_model` field before it ever reaches an
agent. One class per intent, field shapes taken from each intent's workflow
description in docs 02–07. Detailed value validation (e.g. FinCore-specific
constraints) tightens as each intent's owning agent is actually implemented;
these are deliberately permissive placeholders where the source doc doesn't
pin an exact shape yet.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

# --- Admin (doc 03) ---


class IssueDeviceIn(BaseModel):
    emp_id: str
    asset_type: str
    spec: str | None = None
    ticket_ref: str | None = None


class ReturnDeviceIn(BaseModel):
    asset_id: str
    emp_id: str
    condition_report: dict[str, Any] | None = None


class DeviceRepairIn(BaseModel):
    asset_id: str
    issue_description: str


class AddCandidateRecordIn(BaseModel):
    candidate: dict[str, Any]  # CandidateProfile shape, doc 04 §2.2 — firmed up in Sprint 7


class UpdateEmployeeRecordIn(BaseModel):
    emp_id: str
    patch: dict[str, Any]


class DashboardRefreshIn(BaseModel):
    audience_roles: list[str] = Field(default_factory=list)


class ResolveAdminTicketIn(BaseModel):
    ticket_id: str


# --- HR (doc 04) ---


class SourceCandidatesIn(BaseModel):
    role_id: str
    jd_text: str | None = None
    jd_ref: str | None = None
    count: int = 10
    sources: list[str] = Field(default_factory=lambda: ["internal_db"])


class AuditResumeIn(BaseModel):
    candidate_id: str
    resume_uri: str


class ShortlistRoleIn(BaseModel):
    role_id: str
    top_n: int = 10


class PrepareNegotiationIn(BaseModel):
    candidate_id: str
    role_id: str


class PlanTrainingIn(BaseModel):
    emp_id: str | None = None
    team_id: str | None = None
    quarter: str  # e.g. "2026-Q3"


class OnboardEmployeeIn(BaseModel):
    candidate_id: str
    role_id: str
    start_date: date


class OffboardEmployeeIn(BaseModel):
    emp_id: str
    last_day: date
    reason: str


# --- Operations (doc 05) ---


class ProjectHealthReportIn(BaseModel):
    project_id: str


class TimelineRiskScanIn(BaseModel):
    horizon_days: int = 30


class AssignEmployeeProjectIn(BaseModel):
    emp_id: str
    project_id: str
    pct: float = Field(ge=0, le=100)
    from_date: date
    to_date: date | None = None


class CodeAssistSessionIn(BaseModel):
    project_id: str
    mode: str = Field(pattern="^(chat|review|generate|explain|refactor)$")
    input: str
    # doc 05 §5.5's ACL-leakage acceptance test ("engineer without ACL to
    # repo X gets zero code context from X") needs to know *which*
    # engineer is asking — added here since `TaskEnvelope` itself carries
    # no human-identity field (`from_agent` is an AgentId, not a person),
    # same "the payload gains a field once a real requirement needs it"
    # pattern as Sprint 8's `prepare_negotiation` gaining `draft_email`.
    emp_id: str


# --- Finance (doc 06) ---


class GenerateSalarySlipsIn(BaseModel):
    month: str  # "YYYY-MM"
    employee_ids: list[str] | None = None  # None = all active


class RunPayrollIn(BaseModel):
    month: str


class RecordExpenseIn(BaseModel):
    doc_uri: str
    cost_center: str | None = None


class CreateInvoiceIn(BaseModel):
    contract_ref: str
    milestone_id: str | None = None
    items: list[dict[str, Any]] | None = None


class ComputeTaxIn(BaseModel):
    emp_id: str | None = None
    fy: str  # "2026-27"
    kind: str = Field(pattern="^(tds_projection|regime_comparison|gst_worksheet|advance_tax)$")


class MonthCloseIn(BaseModel):
    period: str  # "YYYY-MM"


class FinancialRequirementReportIn(BaseModel):
    horizon_weeks: int = 13


# --- Support (doc 07) ---


class CreateTicketIn(BaseModel):
    channel: str = Field(pattern="^(chat|email|agent|dashboard)$")
    category: str
    subject: str
    body: str


class EscalateTicketIn(BaseModel):
    ticket_id: str
    reason: str


class CrossDeptRequestIn(BaseModel):
    parent_ticket_id: str
    departments: list[str]


class SlaReportIn(BaseModel):
    period_days: int = 7


# --- Composite (doc 00 §5, doc 02 §5) ---


class QuarterlyReviewPackIn(BaseModel):
    quarter: str  # "2026-Q3"


INTENT_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "issue_device": IssueDeviceIn,
    "return_device": ReturnDeviceIn,
    "device_repair": DeviceRepairIn,
    "add_candidate_record": AddCandidateRecordIn,
    "update_employee_record": UpdateEmployeeRecordIn,
    "dashboard_refresh": DashboardRefreshIn,
    "resolve_admin_ticket": ResolveAdminTicketIn,
    "source_candidates": SourceCandidatesIn,
    "audit_resume": AuditResumeIn,
    "shortlist_role": ShortlistRoleIn,
    "prepare_negotiation": PrepareNegotiationIn,
    "plan_training": PlanTrainingIn,
    "onboard_employee": OnboardEmployeeIn,
    "offboard_employee": OffboardEmployeeIn,
    "project_health_report": ProjectHealthReportIn,
    "timeline_risk_scan": TimelineRiskScanIn,
    "assign_employee_project": AssignEmployeeProjectIn,
    "code_assist_session": CodeAssistSessionIn,
    "generate_salary_slips": GenerateSalarySlipsIn,
    "run_payroll": RunPayrollIn,
    "record_expense": RecordExpenseIn,
    "create_invoice": CreateInvoiceIn,
    "compute_tax": ComputeTaxIn,
    "month_close": MonthCloseIn,
    "financial_requirement_report": FinancialRequirementReportIn,
    "create_ticket": CreateTicketIn,
    "escalate_ticket": EscalateTicketIn,
    "cross_dept_request": CrossDeptRequestIn,
    "sla_report": SlaReportIn,
    "quarterly_review_pack": QuarterlyReviewPackIn,
}


def get_payload_model(intent: str) -> type[BaseModel]:
    model = INTENT_PAYLOAD_MODELS.get(intent)
    if model is None:
        raise KeyError(f"no payload model registered for intent: {intent!r}")
    return model


__all__ = ["INTENT_PAYLOAD_MODELS", "get_payload_model"] + [
    name for name in dir() if name.endswith("In") and not name.startswith("_")
]
