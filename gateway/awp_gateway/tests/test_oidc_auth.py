from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _keycloak_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEYCLOAK_URL", "http://keycloak.test:8080")
    monkeypatch.setenv("KEYCLOAK_REALM", "awp")
    monkeypatch.setenv("KEYCLOAK_CLIENT_ID", "awp-gateway")
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("KEYCLOAK_REDIRECT_URI", "http://localhost:8000/api/auth/callback")


class _FakeTokenResponse:
    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeAsyncClient:
    """Stands in for `httpx.AsyncClient` — `callback`'s only outbound call is
    the token-exchange POST; no real Keycloak needed, same fake-the-network
    convention as every other Docker-backed dependency in this repo."""

    response = _FakeTokenResponse(200, {"access_token": "fake-access-token"})
    last_post_data: dict[str, Any] | None = None
    last_post_url: str | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def post(self, url: str, *, data: dict[str, Any]) -> _FakeTokenResponse:
        _FakeAsyncClient.last_post_data = data
        _FakeAsyncClient.last_post_url = url
        return _FakeAsyncClient.response


@pytest.fixture(autouse=True)
def _fake_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeAsyncClient.response = _FakeTokenResponse(200, {"access_token": "fake-access-token"})
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
async def test_login_redirects_to_keycloak_with_pkce(client: AsyncClient) -> None:
    r = await client.get("/api/auth/login", follow_redirects=False)
    assert r.status_code == 307
    location = r.headers["location"]
    assert location.startswith("http://keycloak.test:8080/realms/awp/protocol/openid-connect/auth")
    qs = parse_qs(urlparse(location).query)
    assert qs["client_id"] == ["awp-gateway"]
    assert qs["code_challenge_method"] == ["S256"]
    assert "code_challenge" in qs
    assert "state" in qs
    assert r.cookies.get("oidc_state")
    assert r.cookies.get("oidc_verifier")


@pytest.mark.asyncio
async def test_login_redirects_to_public_url_when_split_from_backend_url(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Live-verified real bug (DEVIATIONS.md #22): a Keycloak-issued token's
    # `iss` is fixed by whatever hostname the *browser* used for /auth, not
    # by whatever address the backend later used for the token exchange —
    # so `/login`'s redirect and `/callback`'s token-exchange POST must be
    # allowed to use genuinely different base URLs.
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "http://public-keycloak.test:8080")
    r = await client.get("/api/auth/login", follow_redirects=False)
    assert r.headers["location"].startswith(
        "http://public-keycloak.test:8080/realms/awp/protocol/openid-connect/auth"
    )


@pytest.mark.asyncio
async def test_callback_token_exchange_uses_backend_url_not_public_url(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "http://public-keycloak.test:8080")
    login_resp = await client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    r = await client.get("/api/auth/callback", params={"code": "abc123", "state": state})
    assert r.status_code == 200
    assert _FakeAsyncClient.last_post_url is not None
    assert _FakeAsyncClient.last_post_url.startswith("http://keycloak.test:8080/realms/awp")
    assert "public-keycloak.test" not in _FakeAsyncClient.last_post_url


@pytest.mark.asyncio
async def test_callback_exchanges_code_for_token(client: AsyncClient) -> None:
    login_resp = await client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]

    r = await client.get("/api/auth/callback", params={"code": "abc123", "state": state})
    assert r.status_code == 200
    assert r.json() == {"token": "fake-access-token"}
    assert _FakeAsyncClient.last_post_data is not None
    assert _FakeAsyncClient.last_post_data["grant_type"] == "authorization_code"
    assert _FakeAsyncClient.last_post_data["code"] == "abc123"
    assert _FakeAsyncClient.last_post_data["client_secret"] == "test-client-secret"


@pytest.mark.asyncio
async def test_callback_rejects_state_mismatch(client: AsyncClient) -> None:
    await client.get("/api/auth/login", follow_redirects=False)
    r = await client.get("/api/auth/callback", params={"code": "abc123", "state": "wrong-state"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_callback_requires_login_cookies_first(client: AsyncClient) -> None:
    r = await client.get("/api/auth/callback", params={"code": "abc123", "state": "some-state"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_surfaces_keycloak_token_exchange_failure(client: AsyncClient) -> None:
    login_resp = await client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(login_resp.headers["location"]).query)["state"][0]
    _FakeAsyncClient.response = _FakeTokenResponse(400, {"error": "invalid_grant"})

    r = await client.get("/api/auth/callback", params={"code": "expired-code", "state": state})
    assert r.status_code == 502
