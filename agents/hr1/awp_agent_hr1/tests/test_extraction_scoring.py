from __future__ import annotations

from awp_shared.candidate_profile import CandidateProfile, Position, RedFlag, RedFlagType

from awp_agent_hr1.extraction_scoring import overlap_recall, score_extraction


def test_score_extraction_perfect_match_is_f1_one() -> None:
    truth = CandidateProfile(
        positions=[Position.new(org="Acme", title="Eng", from_="2022-01", to="2023-01")],
        skills_normalized=["Python", "SQL"],
    )
    score = score_extraction(truth, truth)
    assert score.overall_f1 == 1.0


def test_score_extraction_partial_skill_overlap() -> None:
    truth = CandidateProfile(skills_normalized=["Python", "SQL", "AWS"])
    predicted = CandidateProfile(skills_normalized=["Python", "SQL", "Docker"])
    score = score_extraction(predicted, truth)
    # precision = 2/3, recall = 2/3 -> f1 = 2/3
    assert abs(score.skills_f1 - 2 / 3) < 1e-9


def test_score_extraction_empty_predicted_is_zero() -> None:
    truth = CandidateProfile(skills_normalized=["Python"])
    predicted = CandidateProfile(skills_normalized=[])
    score = score_extraction(predicted, truth)
    assert score.skills_f1 == 0.0


def test_score_extraction_both_empty_is_perfect() -> None:
    truth = CandidateProfile(skills_normalized=[])
    predicted = CandidateProfile(skills_normalized=[])
    score = score_extraction(predicted, truth)
    assert score.skills_f1 == 1.0


def test_overlap_recall_all_caught() -> None:
    profile_with_flag = CandidateProfile(
        red_flags=[RedFlag(type=RedFlagType.OVERLAP, evidence="x overlaps y")]
    )
    results = [(True, profile_with_flag), (False, CandidateProfile())]
    assert overlap_recall(results) == 1.0


def test_overlap_recall_missed_case() -> None:
    profile_without_flag = CandidateProfile()
    results = [(True, profile_without_flag), (True, profile_without_flag)]
    assert overlap_recall(results) == 0.0


def test_overlap_recall_no_positives_is_perfect() -> None:
    results = [(False, CandidateProfile())]
    assert overlap_recall(results) == 1.0
