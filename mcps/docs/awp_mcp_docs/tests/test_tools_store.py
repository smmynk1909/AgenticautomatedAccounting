import base64

import pytest
from awp_mcp_base.server import AwpMcpServer
from awp_shared.auth import mint_service_jwt
from awp_shared.errors import PermissionDeniedError, ValidationError


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _write_token() -> str:
    return mint_service_jwt("ADM-1", ["docs.write"])


def _read_token() -> str:
    return mint_service_jwt("ADM-1", ["docs.read"])


@pytest.mark.asyncio
async def test_store_and_get_public_file_round_trips(docs_server: AwpMcpServer) -> None:
    content = base64.b64encode(b"hello world").decode("ascii")
    stored = await docs_server.dispatch_raw(
        "store_file",
        {"content_base64": content, "filename": "note.txt", "content_type": "text/plain"},
        _headers(_write_token()),
    )
    assert stored["uri"].startswith("minio://")

    fetched = await docs_server.dispatch_raw(
        "get_file", {"uri": stored["uri"]}, _headers(_read_token())
    )
    assert base64.b64decode(fetched["content_base64"]) == b"hello world"
    assert fetched["filename"] == "note.txt"
    assert fetched["content_type"] == "text/plain"


@pytest.mark.asyncio
async def test_get_file_denies_out_of_scope_principal(docs_server: AwpMcpServer) -> None:
    content = base64.b64encode(b"secret").decode("ascii")
    stored = await docs_server.dispatch_raw(
        "store_file",
        {
            "content_base64": content,
            "filename": "salary.pdf",
            "scope": ["hr-admin"],
        },
        _headers(_write_token()),
    )

    # A service principal (mint_service_jwt) always carries roles=[] — it
    # never intersects a non-"public" scope, so this exercises the deny path.
    with pytest.raises(PermissionDeniedError):
        await docs_server.dispatch_raw("get_file", {"uri": stored["uri"]}, _headers(_read_token()))


@pytest.mark.asyncio
async def test_store_file_requires_fields(docs_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await docs_server.dispatch_raw(
            "store_file", {"filename": "x.txt"}, _headers(_write_token())
        )


@pytest.mark.asyncio
async def test_store_file_rejects_invalid_base64(docs_server: AwpMcpServer) -> None:
    with pytest.raises(ValidationError):
        await docs_server.dispatch_raw(
            "store_file",
            {"content_base64": "not-valid-base64!!", "filename": "x.txt"},
            _headers(_write_token()),
        )


@pytest.mark.asyncio
async def test_get_file_missing_uri_404s(docs_server: AwpMcpServer) -> None:
    from awp_shared.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await docs_server.dispatch_raw(
            "get_file",
            {"uri": "minio://test-docs-bucket/does/not/exist"},
            _headers(_read_token()),
        )
