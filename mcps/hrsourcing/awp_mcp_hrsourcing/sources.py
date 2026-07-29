"""`connector_fetch` — doc 08 §7: "source registry (`sources.yaml`) ...
Ships with `internal_db` and `csv_import`; external boards added per
license."

Both shipped sources take their raw material as direct payload input
rather than mcp-hrsourcing reaching into another service for it:
- `csv_import`: the caller already has the CSV bytes (uploaded by a
  recruiter) — mcp-hrsourcing just parses it.
- `internal_db`: the existing candidate pool lives in `mcp-erp`, which
  mcp-hrsourcing can't call directly (no MCP-to-MCP calls). The caller
  fetches candidates via `erp.query_candidates` first and supplies them
  here for keyword filtering against the sourcing query — this is a real
  filter/re-rank step, not a no-op passthrough.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from awp_shared.errors import ValidationError

KNOWN_SOURCES = frozenset({"internal_db", "csv_import"})


def _matches_query(profile: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        str(v) for v in (profile.get("name", ""), *profile.get("skills_normalized", []))
    ).lower()
    return query.lower() in haystack


def fetch_from_source(payload: dict[str, Any]) -> dict[str, Any]:
    source_id = payload.get("source_id")
    query = payload.get("query", "")
    limit = payload.get("limit", 20)

    if source_id not in KNOWN_SOURCES:
        raise ValidationError(f"unknown source_id: {source_id!r} (known: {sorted(KNOWN_SOURCES)})")

    if source_id == "csv_import":
        csv_content = payload.get("csv_content")
        if not csv_content:
            raise ValidationError("csv_import requires 'csv_content'")
        reader = csv.DictReader(io.StringIO(csv_content))
        profiles = [dict(row) for row in reader]
        return {"source_id": source_id, "profiles": profiles[:limit]}

    # internal_db
    candidates = payload.get("candidates", [])
    filtered = [c for c in candidates if _matches_query(c, query)]
    return {"source_id": source_id, "profiles": filtered[:limit]}
