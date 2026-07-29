import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import NotFoundError, ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _render_token() -> str:
    return mint_service_jwt("ADM-1", ["docs.render"])


_ISSUANCE_DATA = {
    "issued_at": "2026-07-26",
    "asset": {
        "id": "AST-1",
        "type": "laptop",
        "make_model": "Dell 5420",
        "serial": "SN123",
        "value": "80000",
    },
    "employee": {"name": "Asha Rao", "emp_id": "EMP-1", "dept_id": "ENG"},
    "ticket_ref": "TCK-1",
}


@pytest.mark.asyncio
async def test_render_pdf_issuance_form_success(docs_server: AwpMcpServer) -> None:
    result = await docs_server.dispatch_raw(
        "render_pdf",
        {"template_id": "issuance_form_v1", "data": _ISSUANCE_DATA},
        _headers(_render_token()),
    )
    assert result["template_id"] == "issuance_form_v1"
    assert result["uri"].startswith("minio://")


_SALARY_SLIP_DATA = {
    "month": "2026-06",
    "employee": {"name": "Asha Rao", "emp_id": "EMP-1", "dept_id": "ENG"},
    "earnings": {"basic": "50000", "hra": "20000"},
    "deductions": {"pf": "1800", "tds": "4030"},
    "gross": "70000",
    "net": "64170",
}

_INVOICE_DATA = {
    "number": "INV/2026-27/000001",
    "client": "Acme Corp",
    "gst_treatment": "intra_state",
    "lines": [{"description": "Consulting", "quantity": "10", "unit_price": "5000"}],
    "subtotal": "50000.00",
    "cgst": "4500.00",
    "sgst": "4500.00",
    "igst": "0",
    "total": "59000.00",
}


@pytest.mark.asyncio
async def test_render_pdf_salary_slip_success(docs_server: AwpMcpServer) -> None:
    result = await docs_server.dispatch_raw(
        "render_pdf",
        {"template_id": "salary_slip_v1", "data": _SALARY_SLIP_DATA},
        _headers(_render_token()),
    )
    assert result["template_id"] == "salary_slip_v1"
    assert result["uri"].startswith("minio://")


@pytest.mark.asyncio
async def test_render_pdf_invoice_gst_success(docs_server: AwpMcpServer) -> None:
    result = await docs_server.dispatch_raw(
        "render_pdf",
        {"template_id": "invoice_gst_v1", "data": _INVOICE_DATA},
        _headers(_render_token()),
    )
    assert result["template_id"] == "invoice_gst_v1"
    assert result["uri"].startswith("minio://")


@pytest.mark.asyncio
async def test_render_pdf_unbuilt_template_404s(docs_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await docs_server.dispatch_raw(
            "render_pdf",
            {"template_id": "offer_letter_v1", "data": {}},
            _headers(_render_token()),
        )


@pytest.mark.asyncio
async def test_render_pdf_requires_template_id(docs_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await docs_server.dispatch_raw("render_pdf", {"data": {}}, _headers(_render_token()))


@pytest.mark.asyncio
async def test_render_docx_always_404s(docs_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await docs_server.dispatch_raw(
            "render_docx",
            {"template_id": "offer_letter_v1"},
            _headers(_render_token()),
        )


@pytest.mark.asyncio
async def test_render_xlsx_generic_success(docs_server: AwpMcpServer) -> None:
    spec = {
        "filename": "assets.xlsx",
        "sheets": [
            {"name": "Assets", "rows": [["id", "type"], ["AST-1", "laptop"]]},
        ],
    }
    result = await docs_server.dispatch_raw(
        "render_xlsx", {"spec": spec}, _headers(_render_token())
    )
    assert result["uri"].startswith("minio://")


@pytest.mark.asyncio
async def test_render_xlsx_requires_sheets(docs_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await docs_server.dispatch_raw("render_xlsx", {"spec": {}}, _headers(_render_token()))
