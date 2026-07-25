"""Timezone-normalization helper.

SQLAlchemy's sqlite dialect silently drops tzinfo on `DateTime(timezone=True)`
round-trips (its default storage format has no offset field, so values come
back naive even though they went in timezone-aware) — Postgres/asyncpg
doesn't have this problem (`TIMESTAMPTZ` round-trips tzinfo correctly), but
every unit test in this repo runs against sqlite. Comparing a DB-read
datetime against a fresh `datetime.now(timezone.utc)` therefore raises
`TypeError: can't compare offset-naive and offset-aware datetimes` the
moment a naive value slips through — silently, only in tests, which is the
worst way to find out. Every comparison against a DB-read datetime should
go through this first.
"""

from __future__ import annotations

from datetime import UTC, datetime


def ensure_aware_utc(value: datetime) -> datetime:
    """Every datetime this system stores is UTC at write time (`datetime.now(timezone.utc)`,
    doc 11 §7 conventions); a naive value read back is assumed to be that same UTC instant
    with its tzinfo merely lost in transit, not a genuinely different naive-local value."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
