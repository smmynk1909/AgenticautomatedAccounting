from __future__ import annotations

from awp_agent_adm1 import assetkeeper


def test_build_issuance_pdf_data_maps_fields() -> None:
    employee = {"emp_id": "EMP-1", "name": "Asha Rao", "dept_id": "ENG"}
    asset = {
        "id": "AST-1",
        "type": "laptop",
        "make_model": "Dell 5420",
        "serial": "SN1",
        "value": "55000.00",
    }

    data = assetkeeper.build_issuance_pdf_data(employee, asset, "TKT-1")

    assert data["employee"] == {"name": "Asha Rao", "emp_id": "EMP-1", "dept_id": "ENG"}
    assert data["asset"]["id"] == "AST-1"
    assert data["asset"]["value"] == "55000.00"
    assert data["ticket_ref"] == "TKT-1"
    assert "issued_at" in data


def test_build_issuance_pdf_data_no_ticket_ref() -> None:
    employee = {"emp_id": "EMP-1", "name": "Asha Rao", "dept_id": "ENG"}
    asset = {
        "id": "AST-1",
        "type": "laptop",
        "make_model": "Dell 5420",
        "serial": None,
        "value": "55000.00",
    }
    data = assetkeeper.build_issuance_pdf_data(employee, asset, None)
    assert data["ticket_ref"] is None
    assert data["asset"]["serial"] is None


def test_approval_request_payload_matches_erp_shape() -> None:
    reservation = {"reservation_id": "RES-1", "asset_id": "AST-1"}
    asset = {"id": "AST-1", "value": "75000.00"}
    payload = assetkeeper.approval_request_payload(reservation, asset)
    assert payload == {"reservation_id": "RES-1", "asset_id": "AST-1", "value": "75000.00"}
