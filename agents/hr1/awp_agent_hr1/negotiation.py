"""HR-1d NegotiationDesk — doc 04 §2.4. The agent prepares and drafts;
humans negotiate final numbers and send. `open`/`target`/`walk_away` are
pure code off the salary band (deterministic-first, same philosophy as
`shortlister.py`) — only the talk track (recruiter-internal prose) goes
through the LLM, and only after the numbers already exist, same
"LLM writes text, never invents facts" split as `justify.py`.
"""

from __future__ import annotations

from typing import Any

from awp_agent_base.protocols import LLMLike, MCPLike
from awp_shared.errors import ValidationError
from pydantic import BaseModel, Field

# doc 04 §2.4's exact non-cash lever menu — a real system would filter this
# by policy eligibility, but no such policy table exists in this build
# (out of scope for doc 12 §5's S8 DoD), so the full doc-named menu is
# offered as-is rather than a fabricated subset.
NON_CASH_LEVERS = ["joining bonus", "LTA", "learning budget", "remote days"]


class SalaryBand(BaseModel):
    grade: str
    min: float
    mid: float
    max: float
    currency: str = "INR"


class MarketBenchmark(BaseModel):
    range_low: float | None = None
    range_high: float | None = None
    source_doc_id: str | None = None
    as_of: str | None = None

    @property
    def known(self) -> bool:
        return self.source_doc_id is not None


class CandidateAsk(BaseModel):
    current_ctc: float | None = None
    expected_ctc: float | None = None
    competing_offers: list[str] = Field(default_factory=list)
    leverage_notes: str = ""


class Recommendation(BaseModel):
    open: float
    target: float
    walk_away: float
    non_cash_levers: list[str] = Field(default_factory=lambda: list(NON_CASH_LEVERS))


class ObjectionResponse(BaseModel):
    objection: str
    response: str


class TalkTrack(BaseModel):
    pairs: list[ObjectionResponse] = Field(default_factory=list)


class NegotiationPack(BaseModel):
    candidate_id: str
    role_id: str
    band: SalaryBand
    market: MarketBenchmark
    candidate: CandidateAsk
    recommendation: Recommendation
    talk_track: list[ObjectionResponse] = Field(default_factory=list)


def compute_recommendation(band: SalaryBand) -> Recommendation:
    """doc 04 §2.4: "open / target / walk-away numbers". Deterministic band
    positioning — open near the band midpoint (room to move up), target
    halfway between mid and max, walk-away at the band ceiling (never
    offered, the number beyond which the role would need re-banding)."""
    return Recommendation(
        open=round(band.mid, 2),
        target=round(band.mid + 0.5 * (band.max - band.mid), 2),
        walk_away=round(band.max, 2),
    )


_TALK_TRACK_SYSTEM_PROMPT = """You write a recruiter's internal negotiation
talk track — never shown to the candidate. Rules:
1. Produce exactly 5 objection-response pairs.
2. Base every response only on the band/market/recommendation facts given
   to you — never invent numbers or claims not present there.
3. Do not mention age, gender, religion, or marital status."""


async def write_talk_track(
    llm: LLMLike,
    band: SalaryBand,
    market: MarketBenchmark,
    recommendation: Recommendation,
) -> list[ObjectionResponse]:
    facts = (
        f"band={band.model_dump()}, market={market.model_dump()}, "
        f"recommendation={recommendation.model_dump()}"
    )
    resp = await llm.chat(
        messages=[
            {"role": "system", "content": _TALK_TRACK_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Facts: {facts}\n\nWrite the 5-pair talk track.",
            },
        ],
        guided_json=TalkTrack,
        profile="draft",
    )
    track = TalkTrack.model_validate_json(resp.content or "{}")
    return track.pairs


async def _get_salary_band(mcp: MCPLike, grade: str) -> SalaryBand:
    result = await mcp.call("erp", "query_policies", {"domain": "salary_bands", "grade": grade})
    rows = result.get("policies", [])
    if not rows:
        raise ValidationError(f"no salary_bands policy row for grade {grade!r}")
    row = rows[0]
    return SalaryBand(
        grade=row["grade"],
        min=row["min"],
        mid=row["mid"],
        max=row["max"],
        currency=row.get("currency", "INR"),
    )


async def _get_market_benchmark(mcp: MCPLike, role_title: str) -> MarketBenchmark:
    result = await mcp.call(
        "search", "search_kb", {"corpus": "market_intel", "query": role_title, "k": 1}
    )
    hits = result.get("results", [])
    if not hits:
        # doc 04 §2.5/§4: "Market claims require a market_intel citation
        # with date; otherwise say unknown" — same rule applied here.
        return MarketBenchmark()
    hit = hits[0]
    citation = hit.get("citation", {})
    return MarketBenchmark(
        range_low=hit.get("range_low"),
        range_high=hit.get("range_high"),
        source_doc_id=citation.get("doc_id"),
        as_of=hit.get("as_of"),
    )


async def build_negotiation_pack(
    llm: LLMLike,
    mcp: MCPLike,
    candidate_id: str,
    role_id: str,
    candidate_input: dict[str, Any] | None,
) -> NegotiationPack:
    role = await mcp.call("erp", "get_role", {"role_id": role_id})
    grade = role.get("grade")
    if not grade:
        raise ValidationError(f"role {role_id} has no grade — cannot resolve a salary band")

    band = await _get_salary_band(mcp, grade)
    market = await _get_market_benchmark(mcp, role.get("title", role_id))
    candidate = CandidateAsk.model_validate(candidate_input or {})
    recommendation = compute_recommendation(band)
    talk_track = await write_talk_track(llm, band, market, recommendation)

    return NegotiationPack(
        candidate_id=candidate_id,
        role_id=role_id,
        band=band,
        market=market,
        candidate=candidate,
        recommendation=recommendation,
        talk_track=talk_track,
    )


_EMAIL_SYSTEM_PROMPT = """You draft a candidate-facing offer/negotiation
email. Rules:
1. You may mention ONLY the "open" and "target" numbers and the listed
   non-cash levers — never the walk-away number, never the salary band,
   never any other candidate's or employee's compensation.
2. Do not mention age, gender, religion, or marital status.
3. Professional, concise, no more than 6 sentences."""


async def draft_candidate_email(
    llm: LLMLike, pack: NegotiationPack, candidate_name: str, terms: dict[str, Any] | None
) -> str:
    offer_terms = terms or {}
    facts = (
        f"candidate_name={candidate_name!r}, "
        f"open={pack.recommendation.open}, target={pack.recommendation.target}, "
        f"non_cash_levers={pack.recommendation.non_cash_levers}, "
        f"terms_from_recruiter={offer_terms}"
    )
    resp = await llm.chat(
        messages=[
            {"role": "system", "content": _EMAIL_SYSTEM_PROMPT},
            {"role": "user", "content": f"Facts: {facts}\n\nDraft the email body."},
        ],
        profile="draft",
    )
    return (resp.content or "").strip()
