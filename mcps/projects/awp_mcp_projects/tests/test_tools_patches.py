import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import ValidationError


def _headers() -> dict[str, str]:
    token = mint_service_jwt("OPS-1", ["projects.write", "projects.read"])
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_suggest_patch_persists_artifact(projects_server: AwpMcpServer) -> None:
    result = await projects_server.dispatch_raw(
        "suggest_patch",
        {
            "repo": "awp-admin/svc-a",
            "base_ref": "main",
            "patch": "diff --git a/x b/x\n",
            "rationale": "fixes off-by-one",
        },
        _headers(),
    )
    assert result["status"] == "proposed"
    assert "patch_id" in result


@pytest.mark.asyncio
async def test_suggest_patch_requires_fields(projects_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await projects_server.dispatch_raw(
            "suggest_patch", {"repo": "awp-admin/svc-a"}, _headers()
        )


@pytest.mark.asyncio
async def test_secrets_scan_flags_seeded_credential(projects_server: AwpMcpServer) -> None:
    text = 'AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n'
    result = await projects_server.dispatch_raw("secrets_scan", {"text": text}, _headers())
    assert result["clean"] is False
    assert any(f["kind"] == "aws_access_key_id" for f in result["findings"])
    assert "AKIAIOSFODNN7EXAMPLE" not in result["redacted_text"]


@pytest.mark.asyncio
async def test_secrets_scan_clean_text_reports_clean(projects_server: AwpMcpServer) -> None:
    result = await projects_server.dispatch_raw(
        "secrets_scan", {"text": "def add(a, b):\n    return a + b\n"}, _headers()
    )
    assert result["clean"] is True
    assert result["findings"] == []


@pytest.mark.asyncio
async def test_secrets_scan_requires_text(projects_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await projects_server.dispatch_raw("secrets_scan", {}, _headers())
