from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from awp_scheduler.jobs import _default_jobs_yaml, is_due, load_jobs


def test_load_jobs_reads_the_real_jobs_yaml() -> None:
    jobs = load_jobs()
    names = {j.name for j in jobs}
    assert "run_payroll_monthly" in names
    assert "quarterly_review_pack" in names
    assert len(jobs) == 6


def test_load_jobs_fan_out_job_has_no_payload_fn() -> None:
    jobs = load_jobs()
    job = next(j for j in jobs if j.name == "project_health_report_weekly")
    assert job.fan_out == "active_projects"
    assert job.payload_fn is None


def test_load_jobs_rejects_job_with_neither_payload_fn_nor_fan_out(tmp_path: Path) -> None:
    bad = tmp_path / "jobs.yaml"
    job = {"name": "bad", "schedule": {"hour": 9, "minute": 0}, "intent": "x", "to_agent": "OPS-1"}
    bad.write_text(yaml.safe_dump([job]))
    with pytest.raises(ValueError, match="exactly one"):
        load_jobs(bad)


def test_load_jobs_rejects_job_with_both_payload_fn_and_fan_out(tmp_path: Path) -> None:
    bad = tmp_path / "jobs.yaml"
    bad.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "bad",
                    "schedule": {"hour": 9, "minute": 0},
                    "intent": "x",
                    "to_agent": "OPS-1",
                    "payload_fn": "none",
                    "fan_out": "active_projects",
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="exactly one"):
        load_jobs(bad)


def test_default_jobs_yaml_honors_env_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Same pattern as awp_shared.config's AWP_CONFIG_DIR — required so a
    # non-editable pip install (the Dockerfile) doesn't silently resolve
    # `__file__`-relative to some site-packages ancestor instead of the
    # repo's real scheduler/jobs.yaml.
    fake = tmp_path / "custom_jobs.yaml"
    monkeypatch.setenv("AWP_JOBS_YAML", str(fake))
    assert _default_jobs_yaml() == fake


def test_default_jobs_yaml_falls_back_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWP_JOBS_YAML", raising=False)
    assert _default_jobs_yaml().name == "jobs.yaml"


def test_is_due_daily_matches_only_the_right_minute() -> None:
    schedule = {"hour": 8, "minute": 0}
    assert is_due(schedule, datetime(2026, 7, 26, 8, 0))
    assert not is_due(schedule, datetime(2026, 7, 26, 8, 1))
    assert not is_due(schedule, datetime(2026, 7, 26, 9, 0))


def test_is_due_monthly_checks_day_of_month() -> None:
    schedule = {"day": 25, "hour": 9, "minute": 0}
    assert is_due(schedule, datetime(2026, 7, 25, 9, 0))
    assert not is_due(schedule, datetime(2026, 7, 24, 9, 0))
    assert is_due(schedule, datetime(2026, 8, 25, 9, 0))  # fires every month on the 25th


def test_is_due_weekly_checks_weekday() -> None:
    schedule = {"weekday": 0, "hour": 9, "minute": 0}  # Monday
    monday = datetime(2026, 7, 27, 9, 0)
    assert monday.weekday() == 0
    assert is_due(schedule, monday)
    tuesday = datetime(2026, 7, 28, 9, 0)
    assert not is_due(schedule, tuesday)


def test_is_due_quarterly_checks_quarter_start() -> None:
    schedule = {"quarterly": True, "hour": 9, "minute": 0}
    assert is_due(schedule, datetime(2026, 7, 1, 9, 0))  # Q3 start
    assert not is_due(schedule, datetime(2026, 7, 2, 9, 0))
    assert not is_due(schedule, datetime(2026, 8, 1, 9, 0))  # not a quarter-start month
