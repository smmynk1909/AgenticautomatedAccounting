from __future__ import annotations

from awp_agent_hr1.eval_fixtures import generate_labeled_resumes


def _month_index(ym: str) -> int:
    year, month = ym.split("-")
    return int(year) * 12 + int(month)


def test_generate_labeled_resumes_is_deterministic() -> None:
    a = generate_labeled_resumes(10, seed=42)
    b = generate_labeled_resumes(10, seed=42)
    assert [r.text for r in a] == [r.text for r in b]
    assert [r.ground_truth.model_dump() for r in a] == [r.ground_truth.model_dump() for r in b]


def test_generate_labeled_resumes_returns_requested_count() -> None:
    resumes = generate_labeled_resumes(50, seed=42)
    assert len(resumes) == 50
    assert len({r.id for r in resumes}) == 50


def test_overlap_flag_matches_actual_position_dates() -> None:
    resumes = generate_labeled_resumes(30, seed=42)
    for r in resumes:
        pos1, pos2 = r.ground_truth.positions
        start_a, end_a = _month_index(pos1.from_), _month_index(pos1.to)
        start_b, end_b = _month_index(pos2.from_), _month_index(pos2.to)
        overlap_months = min(end_a, end_b) - max(start_a, start_b)
        assert r.has_real_overlap == (overlap_months > 0)


def test_some_resumes_have_real_overlaps_and_some_dont() -> None:
    resumes = generate_labeled_resumes(30, seed=42)
    assert any(r.has_real_overlap for r in resumes)
    assert any(not r.has_real_overlap for r in resumes)


def test_resume_text_contains_ground_truth_org_names() -> None:
    resumes = generate_labeled_resumes(5, seed=42)
    for r in resumes:
        for pos in r.ground_truth.positions:
            assert pos.org in r.text
