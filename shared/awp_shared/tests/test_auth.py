from datetime import datetime, timezone

import jwt
import pytest
from fakeredis.aioredis import FakeRedis

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
        gate="payroll_run", payload=payload, approvers=["finance_head", "director"], ttl_h=24, jti="jti-1"
    )
    verified = await verify_approval_token(token, "payroll_run", payload, redis=redis)
    assert verified.jti == "jti-1"
    assert verified.approvers == ["finance_head", "director"]


@pytest.mark.asyncio
async def test_approval_token_rejects_replay() -> None:
    redis = _redis()
    payload = {"a": 1}
    token = mint_approval_token(gate="invoice_issue", payload=payload, approvers=["finance_head"], ttl_h=24, jti="jti-2")
    await verify_approval_token(token, "invoice_issue", payload, redis=redis)
    with pytest.raises(ApprovalRequiredError, match="already used"):
        await verify_approval_token(token, "invoice_issue", payload, redis=redis)


@pytest.mark.asyncio
async def test_approval_token_rejects_payload_drift() -> None:
    redis = _redis()
    token = mint_approval_token(
        gate="invoice_issue", payload={"amount": 100}, approvers=["finance_head"], ttl_h=24, jti="jti-3"
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
    import awp_shared.auth as auth_mod

    redis = _redis()
    payload = {"a": 1}
    now = int(datetime.now(timezone.utc).timestamp())
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
    now = int(datetime.now(timezone.utc).timestamp())
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
