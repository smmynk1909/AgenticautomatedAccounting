"""HR-1e TrainingPlanner — doc 04 §2.5. Gap detection is presence-based
(skill required by the role vs. present in `employees.skills`), not
level-based: no proficiency-level data model exists anywhere in this build
(`employees.skills`/`skills_normalized` are both plain name lists, doc 09
§1's DDL sketch has no per-skill level column either) — same "the data
source doesn't exist yet" pattern as `sourcer.py`'s deferred external
connectors. Likewise, "current+next-grade role" (doc 04 §2.5 step 1) needs a
career-ladder table (which role is the next grade up for a given role) that
doesn't exist in this schema — gap analysis here is against the employee's
*current* role only; documented in DEVIATIONS.md.
"""

from __future__ import annotations

from typing import Any

from awp_agent_base.protocols import MCPLike
from awp_shared.errors import ValidationError
from pydantic import BaseModel


class SkillGap(BaseModel):
    skill: str
    current_level: str  # "present" | "absent" — see module docstring
    target_level: str = "required"
    market_demand_score: float = 0.0
    evidence: str = ""


class TrainingItem(BaseModel):
    skill: str
    course: str
    hours: int
    cost: float
    quarter: str


async def _market_demand(mcp: MCPLike, skill: str) -> tuple[float, str]:
    result = await mcp.call(
        "search", "search_kb", {"corpus": "market_intel", "query": skill, "k": 1}
    )
    hits = result.get("results", [])
    if not hits:
        return 0.0, ""
    hit = hits[0]
    citation = hit.get("citation", {})
    doc_id = citation.get("doc_id") or ""
    return float(hit.get("score", 0.0)), doc_id


async def build_gap_report(mcp: MCPLike, emp_id: str) -> list[SkillGap]:
    employee = await mcp.call("erp", "get_employee", {"emp_id": emp_id})
    role_id = employee.get("role_id")
    if not role_id:
        raise ValidationError(f"employee {emp_id} has no role_id — cannot build a gap report")

    role = await mcp.call("erp", "get_role", {"role_id": role_id})
    role_profile = role.get("role_profile") or {}
    required = sorted(
        {*role_profile.get("must_have", []), *role_profile.get("nice_to_have", [])}
    )
    have = {s.lower() for s in employee.get("skills", [])}

    gaps: list[SkillGap] = []
    for skill in required:
        if skill.lower() in have:
            continue
        demand_score, doc_id = await _market_demand(mcp, skill)
        evidence = f"required by role {role_id}"
        if doc_id:
            evidence += f"; market demand cited in {doc_id}"
        gaps.append(
            SkillGap(
                skill=skill,
                current_level="absent",
                market_demand_score=demand_score,
                evidence=evidence,
            )
        )
    return gaps


async def match_training_plan(
    mcp: MCPLike, gaps: list[SkillGap], quarter: str
) -> list[TrainingItem]:
    """doc 04 §2.5 step 3: match gaps -> `training_catalog` corpus -> draft
    plan. A gap with no catalog match is dropped (nothing to recommend),
    not fabricated — the acceptance bar doesn't require 100% catalog
    coverage, just that every returned item traces to a real corpus hit."""
    items: list[TrainingItem] = []
    for gap in gaps:
        result = await mcp.call(
            "search", "search_kb", {"corpus": "training_catalog", "query": gap.skill, "k": 1}
        )
        hits = result.get("results", [])
        if not hits:
            continue
        hit = hits[0]
        meta = _parse_catalog_hit(hit)
        items.append(
            TrainingItem(
                skill=gap.skill,
                course=meta.get("course") or hit.get("text", gap.skill)[:80],
                hours=int(meta.get("hours", 8)),
                cost=float(meta.get("cost", 0.0)),
                quarter=quarter,
            )
        )
    return items


def _parse_catalog_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """`search_kb` returns free-text chunks, not structured fields — the
    catalog corpus's `upsert_documents` metadata (course/hours/cost) isn't
    threaded through `search_kb`'s hit shape in this build (doc 08 §4 lists
    no such passthrough), so those fields default rather than being
    invented from chunk text. A follow-up doc PR to extend `search_kb`'s
    response with `metadata` would remove this gap."""
    return {}


def summarize_plan(items: list[TrainingItem]) -> dict[str, Any]:
    return {
        "items": [i.model_dump() for i in items],
        "total_hours": sum(i.hours for i in items),
        "total_cost": sum(i.cost for i in items),
    }
