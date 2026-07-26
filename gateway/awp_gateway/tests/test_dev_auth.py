import pytest
from awp_shared.auth import verify_jwt
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dev_login_mints_token_with_roles(client: AsyncClient) -> None:
    r = await client.post("/api/dev/login", json={"user_id": "dev-finance-head"})
    assert r.status_code == 200
    principal = verify_jwt(r.json()["token"])
    assert principal.kind == "user"
    assert "finance_head" in principal.roles


@pytest.mark.asyncio
async def test_dev_login_unknown_user_404s(client: AsyncClient) -> None:
    r = await client.post("/api/dev/login", json={"user_id": "does-not-exist"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_dev_login_disabled_outside_dev_env(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWP_ENV", "prod")
    r = await client.post("/api/dev/login", json={"user_id": "dev-ceo"})
    assert r.status_code == 400
