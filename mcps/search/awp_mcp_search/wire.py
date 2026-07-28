"""JSON-wire-to-Python-type coercion — same rationale as
`mcps/finance/awp_mcp_finance/wire.py`: tool payloads arrive as plain JSON,
so date fields land as ISO strings, not Python objects.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def parse_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"cannot parse as date: {value!r}")
