"""HR-1c's justification-writing half — doc 04 §2.3: "LLM writes a 3-line
justification per shortlisted candidate citing profile fields (no new
facts)." Deliberately separate from `shortlister.py` (which must stay pure
so ranking is testably deterministic) — this module only turns an already-
final ranking into human-readable text, never changes a score or an order.
"""

from __future__ import annotations

from awp_agent_base.protocols import LLMLike
from awp_shared.candidate_profile import CandidateProfile

_SYSTEM_PROMPT = """You write a short justification for why a candidate was
shortlisted for a role. Rules:
1. Exactly 3 lines.
2. Cite only facts present in the candidate profile fields given to you —
   never invent or assume anything not present there.
3. Do not mention age, gender, religion, or marital status even if somehow
   present in the input — these are excluded from evaluation entirely."""


async def write_justification(
    llm: LLMLike, role_profile: dict[str, object], profile: CandidateProfile, score: float
) -> str:
    facts = (
        f"skills_normalized={profile.skills_normalized}, "
        f"total_exp_months={profile.total_exp_months}, "
        f"positions={[p.model_dump(by_alias=True) for p in profile.positions]}, "
        f"audit_score={profile.audit_score.model_dump()}"
    )
    resp = await llm.chat(
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Role must-have skills: {role_profile.get('must_have', [])}\n"
                    f"Candidate profile fields: {facts}\n"
                    f"Match score: {score:.2f}\n\n"
                    "Write the 3-line justification."
                ),
            },
        ],
        profile="draft",
    )
    return (resp.content or "").strip()
