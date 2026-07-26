"""Payload builders referenced by `jobs.yaml`'s `payload_fn` — doc 02 §7."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any


def current_month(now: datetime) -> dict[str, Any]:
    return {"month": now.strftime("%Y-%m")}


def current_quarter(now: datetime) -> dict[str, Any]:
    quarter = (now.month - 1) // 3 + 1
    return {"quarter": f"{now.year}-Q{quarter}"}


def none_payload(now: datetime) -> dict[str, Any]:
    return {}


PAYLOAD_FNS: dict[str, Callable[[datetime], dict[str, Any]]] = {
    "current_month": current_month,
    "current_quarter": current_quarter,
    "none": none_payload,
}
