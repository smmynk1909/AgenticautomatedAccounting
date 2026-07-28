"""Job definitions + due-check logic — doc 02 §7. Pure functions, testable
without a real clock (`is_due` takes an explicit `now`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def _default_jobs_yaml() -> Path:
    # Same fix as awp_shared.config.CONFIG_DIR (DEVIATIONS.md #7): a
    # `__file__`-relative path only resolves correctly in an editable/source
    # checkout. `Dockerfile` pip-installs this package non-editably, which
    # copies files into site-packages and silently breaks that assumption
    # (parents[1] would resolve to some site-packages ancestor, not the
    # repo) — check `AWP_JOBS_YAML` first, fall back to the heuristic only
    # for local dev.
    env_path = os.environ.get("AWP_JOBS_YAML")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[1] / "jobs.yaml"


JOBS_YAML = _default_jobs_yaml()

_QUARTER_START_MONTHS = (1, 4, 7, 10)


@dataclass(frozen=True)
class JobSpec:
    name: str
    schedule: dict[str, Any]
    intent: str
    to_agent: str
    payload_fn: str | None = None
    # Sprint 9: a job whose payload can't be known ahead of the tick (one
    # `project_health_report` per *currently active* project) names an
    # async resolver in `awp_scheduler.fanout.FAN_OUT_FNS` instead of a
    # `payload_fn` — dispatches one TaskEnvelope per payload it returns,
    # each independently deduped. Exactly one of `payload_fn`/`fan_out`
    # must be set; `load_jobs` enforces that at config-load time.
    fan_out: str | None = None


def load_jobs(path: Path = JOBS_YAML) -> list[JobSpec]:
    with path.open("r", encoding="utf-8") as f:
        raw: list[dict[str, Any]] = yaml.safe_load(f) or []
    jobs = []
    for j in raw:
        payload_fn = j.get("payload_fn")
        fan_out = j.get("fan_out")
        if bool(payload_fn) == bool(fan_out):
            raise ValueError(
                f"job {j['name']!r} must set exactly one of 'payload_fn'/'fan_out'"
            )
        jobs.append(
            JobSpec(
                name=j["name"],
                schedule=j["schedule"],
                intent=j["intent"],
                to_agent=j["to_agent"],
                payload_fn=payload_fn,
                fan_out=fan_out,
            )
        )
    return jobs


def is_due(schedule: dict[str, Any], now: datetime) -> bool:
    """A minute-granularity match against `now` — the scheduler polls once a
    minute (`awp_scheduler.main.POLL_INTERVAL_S`), so this only needs to be
    precise to the minute, not wall-clock cron-exact."""
    if "day" in schedule and now.day != schedule["day"]:
        return False
    if "weekday" in schedule and now.weekday() != schedule["weekday"]:
        return False
    if schedule.get("quarterly") and (now.day != 1 or now.month not in _QUARTER_START_MONTHS):
        return False
    return bool(now.hour == schedule["hour"] and now.minute == schedule["minute"])
