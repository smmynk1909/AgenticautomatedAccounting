from __future__ import annotations

from awp_agent_fin1.anomaly import flag_anomalies


def test_flags_zero_or_negative_net() -> None:
    lines = [{"emp_id": "EMP-1", "gross": "50000", "net": "0", "deductions": {"tds": "0"}}]
    flags = flag_anomalies(lines)
    assert len(flags) == 1
    assert flags[0]["emp_id"] == "EMP-1"


def test_flags_high_tds_share() -> None:
    lines = [{"emp_id": "EMP-1", "gross": "100000", "net": "40000", "deductions": {"tds": "60000"}}]
    flags = flag_anomalies(lines)
    assert len(flags) == 1
    assert "TDS" in flags[0]["reason"]


def test_no_flags_for_normal_line() -> None:
    lines = [{"emp_id": "EMP-1", "gross": "100000", "net": "80000", "deductions": {"tds": "5000"}}]
    assert flag_anomalies(lines) == []
