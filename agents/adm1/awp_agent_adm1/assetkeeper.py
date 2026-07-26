"""ADM-1a AssetKeeper — doc 03 §2.1 device issuance/return/repair.

Entitlement checks and the `asset_high_value` threshold are enforced by
`mcp-erp` itself (`assign_asset` reads `config/entitlements.yaml`'s
`asset_high_value_threshold_inr` and calls `verify_approval_token` inline
when crossed — doc 11 §3's own pattern) — this module doesn't duplicate that
policy. `nodes.py`'s `issue_device` handler calls `assign_asset` optimistically
(no `approval_token`) and only starts the request-approval detour on an
`ApprovalRequiredError`, so the threshold lives in exactly one place.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def build_issuance_pdf_data(
    employee: dict[str, Any], asset: dict[str, Any], ticket_ref: str | None
) -> dict[str, Any]:
    """Maps mcp-erp's `get_employee`/`get_asset` rows onto
    `mcps/docs/awp_mcp_docs/templates/issuance_form_v1.html.j2`'s fields."""
    return {
        "issued_at": datetime.now(UTC).date().isoformat(),
        "asset": {
            "id": asset["id"],
            "type": asset["type"],
            "make_model": asset["make_model"],
            "serial": asset.get("serial"),
            "value": str(asset["value"]),
        },
        "employee": {
            "name": employee["name"],
            "emp_id": employee["emp_id"],
            "dept_id": employee["dept_id"],
        },
        "ticket_ref": ticket_ref,
    }


def approval_request_payload(reservation: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    """Must match `mcps/erp/awp_mcp_erp/tools_assets.py::assign_asset`'s own
    `verify_approval_token` payload exactly (field-for-field) — that's what
    the approval token's payload-hash check is verifying, not this
    function's opinion of what's relevant."""
    return {
        "reservation_id": reservation["reservation_id"],
        "asset_id": asset["id"],
        "value": str(asset["value"]),
    }
