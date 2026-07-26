"""ADM-1b RegistryKeeper — doc 03 §2.2 people-registry stewardship.

`mcp-erp.upsert_candidate` already does validate -> dedupe -> refuse-on-match
(doc 08 §1: `CONFLICT` with match evidence, never a silent overwrite) and
`upsert_employee` already gates identity-field changes behind
`record_correction` (doc 08 §1's `IDENTITY_FIELDS` check) — this module
doesn't re-implement either policy, only turns their outcomes into the
artifacts doc 03 §2.2 asks for: a human-actionable duplicate-candidate
notice, and the `record` dict `nodes.py` upserts/re-submits with an
approval token.

`propose_merge` isn't called from the duplicate-import path below: it merges
two *existing* candidate rows (`record_a`/`record_b` both need ids), but a
just-rejected `upsert_candidate` call never got one — there is no tool that
inserts-and-flags-as-duplicate in one step. The dashboard item is the actual
"merge proposal, human confirms" artifact for *this* case; `propose_merge`
is for reconciling two records an admin has already both looked at.
"""

from __future__ import annotations

from typing import Any


def build_employee_record(emp_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    return {"emp_id": emp_id, **patch}


def duplicate_candidate_dashboard_item(
    candidate: dict[str, Any], matches: list[dict[str, Any]], source_task_id: str
) -> dict[str, Any]:
    name = candidate.get("name", "unknown")
    match_desc = "; ".join(
        f"{m['candidate_id']} ({m['reason']}, score={m['score']})" for m in matches
    )
    return {
        "audience_roles": ["admin_head"],
        "panel": "registry",
        "severity": "warning",
        "title": f"Possible duplicate candidate: {name}",
        "body": f"New candidate '{name}' matches existing record(s): {match_desc}"[:400],
        "source_task_id": source_task_id,
    }
