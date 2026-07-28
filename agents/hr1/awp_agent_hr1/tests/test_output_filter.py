"""doc 04 §5 acceptance test 3: "Negotiation draft containing a band
ceiling number -> blocked by output filter test."
"""

from __future__ import annotations

from awp_agent_hr1.negotiation import (
    CandidateAsk,
    MarketBenchmark,
    NegotiationPack,
    Recommendation,
    SalaryBand,
)
from awp_agent_hr1.output_filter import check_draft

_BAND = SalaryBand(grade="G3", min=60000, mid=80000, max=100000)
_REC = Recommendation(open=80000, target=90000, walk_away=100000)


def _pack() -> NegotiationPack:
    return NegotiationPack(
        candidate_id="C1",
        role_id="R1",
        band=_BAND,
        market=MarketBenchmark(),
        candidate=CandidateAsk(),
        recommendation=_REC,
        talk_track=[],
    )


def test_draft_containing_band_ceiling_is_blocked() -> None:
    draft = "We're delighted to offer you a package up to 100000 per annum."
    violations = check_draft(draft, _pack())
    assert violations
    assert any("recommendation.walk_away" in v for v in violations)


def test_draft_containing_band_ceiling_comma_grouped_is_blocked() -> None:
    draft = "Our absolute ceiling for this role is 100,000."
    violations = check_draft(draft, _pack())
    assert violations


def test_draft_containing_only_open_and_target_is_clean() -> None:
    draft = "We're pleased to offer a starting package of 80000, negotiable up to 90000."
    violations = check_draft(draft, _pack())
    assert violations == []


def test_draft_with_no_numbers_is_clean() -> None:
    draft = "We're excited to have you join the team!"
    assert check_draft(draft, _pack()) == []
