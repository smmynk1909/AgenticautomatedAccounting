"""JSON-wire-to-Python-type coercion helpers — same rationale as
`mcps/erp/awp_mcp_erp/wire.py`: tool payloads arrive as plain JSON, so
date/datetime fields land as ISO strings, not Python objects.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def parse_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"cannot parse as date: {value!r}")


def parse_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"cannot parse as datetime: {value!r}")
