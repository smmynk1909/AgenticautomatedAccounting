"""HR-1c Shortlister — doc 04 §2.3: "Deterministic-first, LLM-last."
Every number here is pure code; the LLM (in `nodes.py`) only writes a
justification string per already-ranked candidate — doc 04 §5's acceptance
test 2 ("same inputs → same ranking") depends on that split being real,
not just stated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from awp_shared.candidate_profile import CandidateProfile

WEIGHTS = {
    "keyword": 0.35,
    "semantic": 0.25,
    "experience": 0.20,
    "recency": 0.10,
    "consistency": 0.10,
}


@dataclass(frozen=True)
class ScoredCandidate:
    candidate_id: str
    score: float
    breakdown: dict[str, float]
    evidence: str


def keyword_coverage(must_have: list[str], skills: list[str]) -> float:
    if not must_have:
        return 1.0
    have = {s.lower() for s in skills}
    matched = sum(1 for m in must_have if m.lower() in have)
    return matched / len(must_have)


def experience_fit(min_exp_months: int, total_exp_months: int) -> float:
    if min_exp_months <= 0:
        return 1.0
    return min(1.0, total_exp_months / min_exp_months)


def recency_of_relevant_skills(positions: list[dict[str, Any]], must_have: list[str]) -> float:
    """1.0 if the most recent position's skills cover any must-have skill,
    decaying by 0.25 per position back it takes to find one (0 if none do).
    """
    if not must_have or not positions:
        return 0.0
    must_have_l = {m.lower() for m in must_have}
    # positions assumed most-recent-first, matching Position ordering
    # convention used everywhere else `positions` lists appear in this build.
    for i, pos in enumerate(positions):
        skills = {s.lower() for s in pos.get("skills", [])}
        if skills & must_have_l:
            return max(0.0, 1.0 - 0.25 * i)
    return 0.0


def hard_filters_pass(profile: CandidateProfile, role_profile: dict[str, Any]) -> bool:
    location = role_profile.get("location")
    if location and profile.contact.email is None and profile.contact.phone is None:
        # no way to verify location-adjacent contactability at all — treat
        # as a filter failure rather than silently passing.
        return False
    min_exp = role_profile.get("min_exp_months", 0)
    # a candidate with less than half the minimum experience never clears
    # the bar regardless of other scores — a hard floor, not a soft penalty.
    if min_exp and profile.total_exp_months < min_exp * 0.5:
        return False
    return True


def score_candidate(
    *, semantic_score: float, profile: CandidateProfile, role_profile: dict[str, Any]
) -> ScoredCandidate | None:
    if not hard_filters_pass(profile, role_profile):
        return None

    must_have = role_profile.get("must_have", [])
    kw = keyword_coverage(must_have, profile.skills_normalized)
    exp = experience_fit(role_profile.get("min_exp_months", 0), profile.total_exp_months)
    recency = recency_of_relevant_skills([p.model_dump() for p in profile.positions], must_have)
    consistency = profile.audit_score.consistency

    breakdown = {
        "keyword": kw,
        "semantic": max(0.0, min(1.0, semantic_score)),
        "experience": exp,
        "recency": recency,
        "consistency": consistency,
    }
    total = sum(WEIGHTS[k] * v for k, v in breakdown.items())
    return ScoredCandidate(
        candidate_id=profile.name,  # overwritten with the real id by the caller
        score=total,
        breakdown=breakdown,
        evidence=f"skills={profile.skills_normalized}, exp_months={profile.total_exp_months}",
    )


def rank_candidates(
    candidates: list[tuple[str, float, CandidateProfile]], role_profile: dict[str, Any]
) -> list[ScoredCandidate]:
    """`candidates`: `(candidate_id, semantic_score, profile)` triples."""
    scored = []
    for candidate_id, semantic_score, profile in candidates:
        result = score_candidate(
            semantic_score=semantic_score, profile=profile, role_profile=role_profile
        )
        if result is not None:
            scored.append(
                ScoredCandidate(
                    candidate_id=candidate_id,
                    score=result.score,
                    breakdown=result.breakdown,
                    evidence=result.evidence,
                )
            )
    # deterministic tie-break on candidate_id so equal scores don't depend
    # on input order (Python's sort is stable, but input order itself
    # isn't guaranteed stable across calls to mcp-search).
    scored.sort(key=lambda c: (-c.score, c.candidate_id))
    return scored
