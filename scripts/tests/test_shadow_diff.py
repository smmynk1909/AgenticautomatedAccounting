from __future__ import annotations

import pytest

from scripts.shadow_diff import compare


def test_compare_clean_when_all_match() -> None:
    computed = [{"emp_id": "EMP-1", "net": "73970.00"}, {"emp_id": "EMP-2", "net": "18842.50"}]
    manual = [{"emp_id": "EMP-1", "net": "73970.00"}, {"emp_id": "EMP-2", "net": "18842.50"}]
    report = compare(computed, manual)
    assert report.clean
    assert report.matched == 2
    assert report.mismatched == []


def test_compare_flags_rupee_mismatch() -> None:
    computed = [{"emp_id": "EMP-1", "net": "73970.00"}]
    manual = [{"emp_id": "EMP-1", "net": "73970.01"}]  # one paisa off
    report = compare(computed, manual)
    assert not report.clean
    assert len(report.mismatched) == 1
    assert report.mismatched[0].delta == "-0.01"


def test_compare_flags_missing_employees_both_directions() -> None:
    computed = [{"emp_id": "EMP-1", "net": "1000.00"}, {"emp_id": "EMP-2", "net": "2000.00"}]
    manual = [{"emp_id": "EMP-1", "net": "1000.00"}, {"emp_id": "EMP-3", "net": "3000.00"}]
    report = compare(computed, manual)
    assert not report.clean
    assert report.missing_in_manual == ["EMP-2"]
    assert report.missing_in_computed == ["EMP-3"]


def test_compare_malformed_line_raises() -> None:
    with pytest.raises(ValueError, match="malformed"):
        compare([{"emp_id": "EMP-1"}], [])  # missing 'net'
