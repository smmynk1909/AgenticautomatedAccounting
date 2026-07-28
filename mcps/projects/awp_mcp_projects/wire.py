"""JSON-wire-to-Python-type coercion — see mcps/erp/awp_mcp_erp/wire.py's
module docstring for the full rationale; same helper, duplicated per-MCP-
server rather than shared (established convention across this codebase)."""

from __future__ import annotations

from datetime import date
from typing import Any


def parse_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise TypeError(f"cannot parse as date: {value!r}")
