from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fakeredis.aioredis import FakeRedis
from jwt import PyJWKClient

import awp_shared.auth as auth_mod
from awp_shared.auth import (
    canonical_payload_hash,
    mint_approval_token,
    mint_service_jwt,
    mint_user_jwt,
    require_scopes,
    verify_approval_token,
    verify_jwt,
)
from awp_shared.errors import ApprovalRequiredError, PermissionDeniedError


def _redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


def _keycloak_token(
    monkeypatch: pytest.MonkeyPatch,
    *,
    claims_override: dict | None = None,
    signing_key: rsa.RSAPublicKey | None = None,
) -> str:
    """Signs a Keycloak-shaped RS256 token with a throwaway keypair and
    monkeypatches `PyJWKClient.get_signing_key_from_jwt` to hand back its
    public half — no real Keycloak/network needed, matching every other
    Docker-backed dependency's fake-in-unit-tests convention in this repo."""
    monkeypatch.setenv("KEYCLOAK_URL", "http://keycloak.test:8080")
    monkeypatch.setenv("KEYCLOAK_REALM", "awp")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "preferred_username": "dev-ceo",
        "realm_access": {"roles": ["ceo", "default-roles-awp"]},
        "iss": "http://keycloak.test:8080/realms/awp",
        "iat": now,
        "exp": now + 900,
    }
    claims.update(claims_override or {})
    token = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-kid"})

    class _FakeSigningKey:
        key = signing_key or public_key

    monkeypatch.setattr(
        PyJWKClient, "get_signing_key_from_jwt", lambda self, t: _FakeSigningKey()
    )
    return token


def test_service_jwt_round_trip() -> None:
    token = mint_service_jwt("FIN-1", ["finance.read", "finance.write"])
    principal = verify_jwt(token)
    assert principal.sub == "FIN-1"
    assert principal.kind == "agent"
    assert principal.scopes == ["finance.read", "finance.write"]


def test_user_jwt_round_trip() -> None:
    token = mint_user_jwt("dev-finance-head", ["finance_head", "finance"])
    principal = verify_jwt(token)
    assert principal.sub == "dev-finance-head"
    assert principal.kind == "user"
    assert "finance_head" in principal.roles


def test_verify_jwt_rejects_garbage_token() -> None:
    with pytest.raises(PermissionDeniedError):
        verify_jwt("not-a-jwt")


def test_verify_jwt_rejects_wrong_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    token = mint_service_jwt("FIN-1", ["finance.read"])
    monkeypatch.setenv("AWP_JWT_ISSUER", "someone-else")
    with pytest.raises(PermissionDeniedError):
        verify_jwt(token)


def test_keycloak_jwt_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    token = _keycloak_token(monkeypatch)
    principal = verify_jwt(token)
    assert principal.sub == "dev-ceo"  # preferred_username, not the opaque sub UUID
    assert principal.kind == "user"
    assert "ceo" in principal.roles
    assert principal.scopes == []


def test_keycloak_jwt_accepts_public_issuer_when_split_from_backend_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Live-verified real bug (DEVIATIONS.md #22): a real Keycloak token's
    # `iss` reflects the *public* hostname (what a browser used for
    # /auth), not KEYCLOAK_URL (what the backend uses to reach Keycloak's
    # APIs) — a token must validate against KEYCLOAK_PUBLIC_URL even
    # though KEYCLOAK_URL points somewhere else entirely.
    token = _keycloak_token(monkeypatch, claims_override={"iss": "http://public-kc.test/realms/awp"})
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "http://public-kc.test")
    principal = verify_jwt(token)
    assert principal.sub == "dev-ceo"


def test_keycloak_jwt_rejects_backend_url_as_issuer_when_split_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The inverse of the above: once KEYCLOAK_PUBLIC_URL is set, a token
    # whose `iss` is the *backend* URL (KEYCLOAK_URL) must NOT validate —
    # that would silently reintroduce the bug this split fixes.
    token = _keycloak_token(monkeypatch)  # iss defaults to KEYCLOAK_URL's value
    monkeypatch.setenv("KEYCLOAK_PUBLIC_URL", "http://public-kc.test")
    with pytest.raises(PermissionDeniedError):
        verify_jwt(token)


def test_keycloak_jwt_rejects_wrong_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Signed with one keypair, but the JWKS lookup (forged/compromised,
    # or simply a stale cached key after rotation) hands back a different
    # one — must fail closed, not silently accept.
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _keycloak_token(monkeypatch, signing_key=other_key.public_key())
    with pytest.raises(PermissionDeniedError):
        verify_jwt(token)


def test_keycloak_jwt_rejects_wrong_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    token = _keycloak_token(monkeypatch, claims_override={"iss": "http://not-us:8080/realms/awp"})
    with pytest.raises(PermissionDeniedError):
        verify_jwt(token)


def test_keycloak_jwt_rejects_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    now = int(datetime.now(UTC).timestamp())
    token = _keycloak_token(monkeypatch, claims_override={"iat": now - 3600, "exp": now - 60})
    with pytest.raises(PermissionDeniedError):
        verify_jwt(token)


def test_verify_jwt_requires_keycloak_url_for_rs256_token(monkeypatch: pytest.MonkeyPatch) -> None:
    # An RS256-header token with KEYCLOAK_URL unset must raise a clear config
    # error, not a confusing signature-verification failure.
    monkeypatch.delenv("KEYCLOAK_URL", raising=False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode({"sub": "x"}, key, algorithm="RS256")
    with pytest.raises(RuntimeError, match="KEYCLOAK_URL"):
        verify_jwt(token)


def test_require_scopes_raises_on_missing() -> None:
    principal = verify_jwt(mint_service_jwt("ADM-1", ["erp.people.read"]))
    with pytest.raises(PermissionDeniedError):
        require_scopes(principal, ["erp.people.write"])


def test_require_scopes_passes_when_satisfied() -> None:
    principal = verify_jwt(mint_service_jwt("ADM-1", ["erp.people.read", "erp.people.write"]))
    require_scopes(principal, ["erp.people.read"])  # no raise


def test_canonical_payload_hash_is_order_independent() -> None:
    a = canonical_payload_hash({"x": 1, "y": 2})
    b = canonical_payload_hash({"y": 2, "x": 1})
    assert a == b


@pytest.mark.asyncio
async def test_approval_token_happy_path() -> None:
    redis = _redis()
    payload = {"register_id": "r1", "totals": {"net": 100000}}
    token = mint_approval_token(
        gate="payroll_run",
        payload=payload,
        approvers=["finance_head", "director"],
        ttl_h=24,
        jti="jti-1",
    )
    verified = await verify_approval_token(token, "payroll_run", payload, redis=redis)
    assert verified.jti == "jti-1"
    assert verified.approvers == ["finance_head", "director"]


@pytest.mark.asyncio
async def test_approval_token_rejects_replay() -> None:
    redis = _redis()
    payload = {"a": 1}
    token = mint_approval_token(
        gate="invoice_issue", payload=payload, approvers=["finance_head"], ttl_h=24, jti="jti-2"
    )
    await verify_approval_token(token, "invoice_issue", payload, redis=redis)
    with pytest.raises(ApprovalRequiredError, match="already used"):
        await verify_approval_token(token, "invoice_issue", payload, redis=redis)


@pytest.mark.asyncio
async def test_approval_token_rejects_payload_drift() -> None:
    redis = _redis()
    token = mint_approval_token(
        gate="invoice_issue",
        payload={"amount": 100},
        approvers=["finance_head"],
        ttl_h=24,
        jti="jti-3",
    )
    with pytest.raises(ApprovalRequiredError, match="payload hash mismatch"):
        await verify_approval_token(token, "invoice_issue", {"amount": 999}, redis=redis)


@pytest.mark.asyncio
async def test_approval_token_rejects_wrong_gate() -> None:
    redis = _redis()
    token = mint_approval_token(
        gate="invoice_issue", payload={"a": 1}, approvers=["finance_head"], ttl_h=24, jti="jti-4"
    )
    with pytest.raises(ApprovalRequiredError, match="gate"):
        await verify_approval_token(token, "payroll_run", {"a": 1}, redis=redis)


@pytest.mark.asyncio
async def test_approval_token_rejects_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _redis()
    payload = {"a": 1}
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "jti": "jti-5",
        "gate": "invoice_issue",
        "payload_hash": canonical_payload_hash(payload),
        "approvers": ["finance_head"],
        "iss": "awp-test",
        "iat": now - 3600,
        "exp": now - 60,  # already expired
    }
    expired_token = jwt.encode(claims, auth_mod._approval_secret(), algorithm="HS256")
    with pytest.raises(ApprovalRequiredError, match="expired"):
        await verify_approval_token(expired_token, "invoice_issue", payload, redis=redis)


@pytest.mark.asyncio
async def test_approval_token_rejects_forged_signature() -> None:
    redis = _redis()
    payload = {"a": 1}
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "jti": "jti-6",
        "gate": "invoice_issue",
        "payload_hash": canonical_payload_hash(payload),
        "approvers": ["finance_head"],
        "iss": "awp-test",
        "iat": now,
        "exp": now + 3600,
    }
    # signed with the *service* secret, not the approval secret — simulates an
    # agent trying to mint its own "approval" out of a valid service JWT key.
    forged = jwt.encode(claims, "test-service-secret-32-bytes-min-xxxx", algorithm="HS256")
    with pytest.raises(ApprovalRequiredError):
        await verify_approval_token(forged, "invoice_issue", payload, redis=redis)
