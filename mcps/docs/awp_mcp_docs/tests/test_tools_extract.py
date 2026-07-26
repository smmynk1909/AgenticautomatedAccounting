import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import NotFoundError, ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _render_token() -> str:
    return mint_service_jwt("ADM-1", ["docs.render"])


def _read_token() -> str:
    return mint_service_jwt("ADM-1", ["docs.read"])


@pytest.mark.asyncio
async def test_extract_text_reads_rendered_pdf(docs_server: AwpMcpServer) -> None:
    rendered = await docs_server.dispatch_raw(
        "render_pdf",
        {
            "template_id": "issuance_form_v1",
            "data": {
                "issued_at": "2026-07-26",
                "asset": {
                    "id": "AST-1",
                    "type": "laptop",
                    "make_model": "Dell 5420",
                    "serial": "SN123",
                    "value": "80000",
                },
                "employee": {"name": "Asha Rao", "emp_id": "EMP-1", "dept_id": "ENG"},
            },
        },
        _headers(_render_token()),
    )

    result = await docs_server.dispatch_raw(
        "extract_text", {"file_uri": rendered["uri"]}, _headers(_read_token())
    )
    assert "Asset Issuance Form" in result["text"]
    assert "Asha Rao" in result["text"]
    assert len(result["blocks"]) == 1
    assert result["blocks"][0]["page"] == 0


@pytest.mark.asyncio
async def test_extract_text_requires_file_uri(docs_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await docs_server.dispatch_raw("extract_text", {}, _headers(_read_token()))


@pytest.mark.asyncio
async def test_extract_text_missing_file_404s(docs_server: AwpMcpServer) -> None:
    with pytest.raises(NotFoundError):
        await docs_server.dispatch_raw(
            "extract_text",
            {"file_uri": "minio://test-docs-bucket/does/not/exist"},
            _headers(_read_token()),
        )
