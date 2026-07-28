"""doc 04 §5 acceptance test 4: "Masked-cohort shortlist parity within
tolerance on synthetic bias suite." `CandidateProfile` has no protected-
attribute fields at all (doc 04 §2.3's fairness rule: age/gender/religion/
marital status are excluded from the schema, not merely masked at
inference time) — the only thing this suite can vary between cohorts is a
name-derived proxy, and `shortlister.score_candidate` never reads `name`
as a scoring input (only as a placeholder immediately overwritten by the
caller's real `candidate_id`). So cohort parity here isn't an approximate
statistical property to tolerate noise in — it's a structural guarantee:
two cohorts identical on every *scored* dimension must produce identical
shortlist rates, exactly, every time. This test proves that guarantee
holds against the real ranking code, not just against the doc's claim.
"""

from __future__ import annotations

import random

from awp_shared.candidate_profile import AuditScore, CandidateProfile, Position

from awp_agent_hr1.shortlister import rank_candidates

_ROLE_PROFILE = {"must_have": ["Python", "SQL"], "min_exp_months": 24}

# Two name pools standing in for different demographic-coded cohorts —
# everything else about each cohort's candidates is generated identically.
_COHORT_A_NAMES = ["Aarav Sharma", "Vihaan Gupta", "Ishaan Verma", "Kabir Singh", "Arjun Rao"]
_COHORT_B_NAMES = ["Fatima Khan", "Aisha Ahmed", "Zainab Malik", "Noor Sheikh", "Sana Iqbal"]


def _make_profile(name: str, seed: int) -> CandidateProfile:
    # `seed` varies the (name-independent) merit signal across a cohort so
    # this isn't just "every candidate is identical" — some candidates in
    # each cohort clear the bar and some don't, on the same distribution.
    exp_months = 24 + (seed % 3) * 12
    consistency = 0.6 + (seed % 4) * 0.1
    return CandidateProfile(
        name=name,
        total_exp_months=exp_months,
        positions=[Position.new(org="Acme", title="Engineer", skills=["Python", "SQL"])],
        skills_normalized=["Python", "SQL"],
        audit_score=AuditScore(completeness=0.9, consistency=consistency),
    )


def _cohort_triples(
    names: list[str], ids: list[str]
) -> list[tuple[str, float, CandidateProfile]]:
    # `candidate_id` is deliberately NOT derived from `name`: real
    # candidate_ids are opaque UUIDs (mcp-erp's `candidates.id`), uncorrelated
    # with name. `shortlister.rank_candidates` tie-breaks equal scores by
    # `candidate_id` (for determinism) — an id scheme that happened to
    # correlate with cohort (e.g. an earlier draft of this test using
    # `f"{name}-id"`) would leak cohort membership through the tie-break
    # itself, which is a bug in the *test*, not evidence of real bias, since
    # production ids carry no such correlation.
    return [
        (cand_id, 0.8, _make_profile(name, i))
        for i, (name, cand_id) in enumerate(zip(names, ids, strict=True))
    ]


def test_masked_cohort_shortlist_rate_parity() -> None:
    all_ids = [f"cand-{i:02d}" for i in range(len(_COHORT_A_NAMES) + len(_COHORT_B_NAMES))]
    random.Random(7).shuffle(all_ids)
    ids_a, ids_b = all_ids[: len(_COHORT_A_NAMES)], all_ids[len(_COHORT_A_NAMES) :]

    triples = _cohort_triples(_COHORT_A_NAMES, ids_a) + _cohort_triples(_COHORT_B_NAMES, ids_b)
    ranked = rank_candidates(triples, _ROLE_PROFILE)

    # Both cohorts are generated from the same seed sequence, so they share
    # an identical *multiset* of scores: every distinct score value appears
    # in exactly one cohort-A and one cohort-B candidate (a "tied pair").
    # A cutoff that lands mid-pair is inherently unresolvable without a
    # tie-break, and any tie-break (however cohort-blind) then hands that
    # one seat to whichever id happens to sort first — a 1-candidate
    # imbalance that no amount of "fairness" in the tie-break can avoid.
    # `top_n=4` lands on a full tier boundary (two complete score tiers,
    # each contributing exactly one candidate per cohort) so parity is
    # decided by the scoring function alone, never by a tie-break.
    top_n = 4
    shortlisted_ids = {c.candidate_id for c in ranked[:top_n]}

    def shortlist_rate(ids: list[str]) -> float:
        return len(set(ids) & shortlisted_ids) / len(ids)

    rate_a = shortlist_rate(ids_a)
    rate_b = shortlist_rate(ids_b)
    assert rate_a == rate_b


def test_identical_candidates_across_cohorts_score_identically() -> None:
    # Same merit profile, different name-derived cohort — scores (not just
    # the eventual shortlist cut) must match exactly.
    profile_a = _make_profile(_COHORT_A_NAMES[0], seed=1)
    profile_b = _make_profile(_COHORT_B_NAMES[0], seed=1)
    ranked = rank_candidates(
        [("A", 0.8, profile_a), ("B", 0.8, profile_b)], _ROLE_PROFILE
    )
    scores = {c.candidate_id: c.score for c in ranked}
    assert scores["A"] == scores["B"]
