"""JSON-wire-to-Python-type coercion helpers.

Tool payloads arrive as plain JSON (doc 08 §0 wire format, DEVIATIONS.md #6)
— date/datetime fields land as ISO strings, not Python `date`/`datetime`
objects. SQLAlchemy's `Date`/`DateTime` column types expect real Python
objects as bind values; passing a raw string through (especially a
timezone-aware `datetime.isoformat()` string like `"...+00:00"`) silently
mis-stores or mis-parses on at least the sqlite dialect used in tests. Every
tool handler that inserts/updates a date/datetime column from payload input
must go through these first.
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
