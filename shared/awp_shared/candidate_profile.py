"""`CandidateProfile` — doc 04 §2.2's resume-audit extraction schema.
Shared between `mcp-hrsourcing.normalize_profile` (produces it) and
`agents/hr1`'s ResumeAuditor/Shortlister (consume it), so both sides of
that contract can't silently drift — same rationale as `fincore/models.py`
being shared by fincore and mcp-finance.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Contact(BaseModel):
    email: str | None = None
    phone: str | None = None


class Position(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    org: str = ""
    title: str = ""
    from_: str = Field("", alias="from")
    to: str = ""
    skills: list[str] = Field(default_factory=list)

    @classmethod
    def new(
        cls,
        *,
        org: str = "",
        title: str = "",
        from_: str = "",
        to: str = "",
        skills: list[str] | None = None,
    ) -> Position:
        # `from_="..."` keyword construction is valid at runtime
        # (`populate_by_name=True`) but mypy's pydantic plugin only
        # generates `__init__`'s signature from the alias ("from"), not
        # the field name — a known plugin gap, isolated to this one
        # ignore rather than one per call site.
        return cls(org=org, title=title, from_=from_, to=to, skills=skills or [])  # type: ignore[call-arg]


class Gap(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field("", alias="from")
    to: str = ""
    months: int = 0

    @classmethod
    def new(cls, *, from_: str = "", to: str = "", months: int = 0) -> Gap:
        return cls(from_=from_, to=to, months=months)  # type: ignore[call-arg]


class RedFlagType(StrEnum):
    OVERLAP = "overlap"
    INCONSISTENT_DATES = "inconsistent_dates"
    TITLE_INFLATION_SIGNAL = "title_inflation_signal"
    UNVERIFIABLE_CLAIM = "unverifiable_claim"


class RedFlag(BaseModel):
    type: RedFlagType
    evidence: str


class AuditScore(BaseModel):
    completeness: float = 0.0
    consistency: float = 0.0
    relevance_to_role: float | None = None


class CandidateProfile(BaseModel):
    name: str = ""
    contact: Contact = Field(default_factory=Contact)
    total_exp_months: int = 0
    positions: list[Position] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    skills_normalized: list[str] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    red_flags: list[RedFlag] = Field(default_factory=list)
    audit_score: AuditScore = Field(default_factory=AuditScore)
