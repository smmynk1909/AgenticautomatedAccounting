from __future__ import annotations

from awp_shared.candidate_profile import AuditScore, CandidateProfile, Position

from awp_agent_hr1.shortlister import (
    experience_fit,
    hard_filters_pass,
    keyword_coverage,
    rank_candidates,
    recency_of_relevant_skills,
)


def test_keyword_coverage_full_match() -> None:
    assert keyword_coverage(["Python", "SQL"], ["Python", "SQL", "AWS"]) == 1.0


def test_keyword_coverage_partial_match() -> None:
    assert keyword_coverage(["Python", "SQL"], ["Python"]) == 0.5


def test_keyword_coverage_empty_must_have_is_full() -> None:
    assert keyword_coverage([], ["Python"]) == 1.0


def test_experience_fit_meets_minimum() -> None:
    assert experience_fit(24, 36) == 1.0


def test_experience_fit_below_minimum_scales_down() -> None:
    assert experience_fit(24, 12) == 0.5


def test_experience_fit_no_minimum_is_full() -> None:
    assert experience_fit(0, 0) == 1.0


def test_recency_most_recent_position_matches() -> None:
    positions = [{"skills": ["Python"]}, {"skills": ["COBOL"]}]
    assert recency_of_relevant_skills(positions, ["Python"]) == 1.0


def test_recency_older_position_matches_decays() -> None:
    positions = [{"skills": ["COBOL"]}, {"skills": ["Python"]}]
    assert recency_of_relevant_skills(positions, ["Python"]) == 0.75


def test_recency_no_match_is_zero() -> None:
    positions = [{"skills": ["COBOL"]}]
    assert recency_of_relevant_skills(positions, ["Python"]) == 0.0


def test_hard_filters_rejects_insufficient_experience() -> None:
    profile = CandidateProfile(total_exp_months=6)
    assert not hard_filters_pass(profile, {"min_exp_months": 24})


def test_hard_filters_passes_sufficient_experience() -> None:
    profile = CandidateProfile(total_exp_months=30)
    assert hard_filters_pass(profile, {"min_exp_months": 24})


def test_rank_candidates_is_deterministic_across_runs() -> None:
    role_profile = {"must_have": ["Python"], "min_exp_months": 12}
    profile_a = CandidateProfile(
        skills_normalized=["Python"],
        total_exp_months=24,
        positions=[Position.new(skills=["Python"])],
        audit_score=AuditScore(consistency=0.8),
    )
    profile_b = CandidateProfile(
        skills_normalized=["Java"],
        total_exp_months=24,
        positions=[Position.new(skills=["Java"])],
        audit_score=AuditScore(consistency=0.8),
    )
    candidates = [("cand-b", 0.5, profile_b), ("cand-a", 0.5, profile_a)]

    ranked_1 = rank_candidates(candidates, role_profile)
    ranked_2 = rank_candidates(candidates, role_profile)
    assert [c.candidate_id for c in ranked_1] == [c.candidate_id for c in ranked_2]
    assert ranked_1[0].candidate_id == "cand-a"  # matches must_have, ranks higher


def test_rank_candidates_filters_out_hard_filter_failures() -> None:
    role_profile = {"min_exp_months": 60}
    profile = CandidateProfile(total_exp_months=6)
    ranked = rank_candidates([("cand-1", 0.9, profile)], role_profile)
    assert ranked == []
