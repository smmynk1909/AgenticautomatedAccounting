"""Principals, service/user JWTs, and cryptographic HITL approval tokens.

Contract per doc 11 §1.2. **Sprint 11, DEVIATIONS.md #22**: `verify_jwt` now
validates real Keycloak-issued (RS256) human session tokens via a cached
JWKS client, exactly as doc 11 §1.2's `# Keycloak JWKS cached` comment
specifies — DEVIATIONS.md #2's HS256-local-secret placeholder is gone for
*human* tokens. Service (agent) tokens still use the local HS256 scheme
(`mint_service_jwt` is unchanged; doc 11 §1.2's own pseudocode never gives
it a different signature either) — `verify_jwt` picks the right validation
path per-token by its JWT header `alg`, so every caller (`Principal` shape,
`require_scopes`, `verify_approval_token`'s HITL enforcement) is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import Any, Literal

import jwt
from jwt import PyJWKClient
from pydantic import BaseModel
from redis.asyncio import Redis

from awp_shared.errors import ApprovalRequiredError, PermissionDeniedError

ALGORITHM = "HS256"
KEYCLOAK_ALGORITHM = "RS256"


def _issuer() -> str:
    return os.environ.get("AWP_JWT_ISSUER", "awp-dev")


def _service_secret() -> str:
    secret = os.environ.get("AWP_DEV_JWT_SECRET")
    if not secret:
        raise RuntimeError(
            "AWP_DEV_JWT_SECRET not set — copy .env.example to .env (dev-mode auth, "
            "see DEVIATIONS.md #2; a Keycloak JWKS key-source replaces this at Sprint 11)"
        )
    return secret


def _approval_secret() -> str:
    # Deliberately a *different* secret from service JWTs: only mcp-approvals'
    # tokens.py ever signs with this one (doc 08 §5 — no agent scope can mint).
    secret = os.environ.get("AWP_APPROVAL_JWT_SECRET")
    if not secret:
        raise RuntimeError("AWP_APPROVAL_JWT_SECRET not set — copy .env.example to .env")
    return secret


def _utcnow() -> datetime:
    return datetime.now(UTC)


def keycloak_realm_url() -> str:
    """Network-reachable base for the gateway's own outbound calls to
    Keycloak (JWKS fetch, token exchange) — NOT necessarily the string a
    token's `iss` claim contains (see `keycloak_issuer` below). Behind
    Docker these two are genuinely different addresses for the same
    realm; conflating them was a real, live-verified bug (DEVIATIONS.md
    #22) — a token exchanged via one path still carries the *authorization*
    step's hostname in `iss`, not the token-exchange call's own path, so
    validating `iss` against this network-address value fails closed on
    every otherwise-valid token."""
    base = os.environ.get("KEYCLOAK_URL")
    if not base:
        raise RuntimeError(
            "KEYCLOAK_URL not set — required to verify a Keycloak-issued (RS256) "
            "token; a service (HS256) token doesn't need it"
        )
    realm = os.environ.get("KEYCLOAK_REALM", "awp")
    return f"{base.rstrip('/')}/realms/{realm}"


def keycloak_issuer() -> str:
    """The exact `iss` string Keycloak embeds in this realm's tokens —
    fixed by whatever hostname the *browser* used to reach Keycloak's
    `/auth` endpoint (`KEYCLOAK_PUBLIC_URL`), live-verified to persist
    through to the token-exchange response regardless of which address the
    backend itself used to make that call. Falls back to `keycloak_realm_url()`
    when `KEYCLOAK_PUBLIC_URL` isn't set — the common case (tests, a
    non-Docker dev setup) where there's only one address for Keycloak and
    this split doesn't matter."""
    public_base = os.environ.get("KEYCLOAK_PUBLIC_URL")
    if not public_base:
        return keycloak_realm_url()
    realm = os.environ.get("KEYCLOAK_REALM", "awp")
    return f"{public_base.rstrip('/')}/realms/{realm}"


_jwks_client: PyJWKClient | None = None
_jwks_client_base: str | None = None


def _get_jwks_client() -> PyJWKClient:
    """Cached per doc 11 §1.2 (`# Keycloak JWKS cached`) — `PyJWKClient`
    caches keys by `kid` internally and only re-fetches on a cache miss, so
    a Keycloak realm-key rotation is picked up automatically without a
    restart. Fetches from `keycloak_realm_url()` (network-reachable), not
    `keycloak_issuer()` — the *keys* live at whatever address can actually
    be connected to; only the `iss` *string comparison* needs the
    public-facing value. Rebuilt (not just re-cached) if that address ever
    changes within one process — only relevant to tests, which patch it
    per-case."""
    global _jwks_client, _jwks_client_base
    base = keycloak_realm_url()
    if _jwks_client is None or _jwks_client_base != base:
        _jwks_client = PyJWKClient(f"{base}/protocol/openid-connect/certs", cache_keys=True)
        _jwks_client_base = base
    return _jwks_client


class Principal(BaseModel):
    sub: str
    kind: Literal["agent", "user"]
    roles: list[str] = []
    scopes: list[str] = []


class ApprovalToken(BaseModel):
    jti: str
    gate: str
    payload_hash: str
    approvers: list[str]
    exp: datetime


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    """Deterministic hash an approval binds to — any payload drift invalidates the token."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mint_service_jwt(agent_id: str, scopes: list[str], ttl_s: int = 900) -> str:
    now = int(time.time())
    claims = {
        "sub": agent_id,
        "kind": "agent",
        "scopes": scopes,
        "roles": [],
        "iss": _issuer(),
        "iat": now,
        "exp": now + ttl_s,
    }
    return jwt.encode(claims, _service_secret(), algorithm=ALGORITHM)


def mint_user_jwt(user_id: str, roles: list[str], ttl_s: int = 8 * 3600) -> str:
    """Dev-mode human session token — DEVIATIONS.md #2. Gateway's OIDC code flow
    replaces the caller of this at Sprint 11; the token shape is unchanged."""
    now = int(time.time())
    claims = {
        "sub": user_id,
        "kind": "user",
        "roles": roles,
        "scopes": [],
        "iss": _issuer(),
        "iat": now,
        "exp": now + ttl_s,
    }
    return jwt.encode(claims, _service_secret(), algorithm=ALGORITHM)


def verify_jwt(token: str) -> Principal:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise PermissionDeniedError(f"invalid or expired token: {exc}") from exc

    if header.get("alg") == KEYCLOAK_ALGORITHM:
        return _verify_keycloak_jwt(token)

    try:
        data = jwt.decode(token, _service_secret(), algorithms=[ALGORITHM], issuer=_issuer())
    except jwt.PyJWTError as exc:
        raise PermissionDeniedError(f"invalid or expired token: {exc}") from exc
    return Principal(
        sub=data["sub"],
        kind=data.get("kind", "agent"),
        roles=data.get("roles", []),
        scopes=data.get("scopes", []),
    )


def _verify_keycloak_jwt(token: str) -> Principal:
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        data = jwt.decode(
            token,
            signing_key.key,
            algorithms=[KEYCLOAK_ALGORITHM],
            issuer=keycloak_issuer(),
            # Keycloak's default access-token audience is client-dependent
            # (`account`, or a client-configured value) and this build has
            # no audience mapper configured on `awp-gateway` — verifying
            # signature + issuer + expiry is the real security boundary
            # here (a forged/expired token still fails), so `aud` is
            # intentionally not checked. Revisit if a second confidential
            # client is ever added to the realm and audience confusion
            # between them becomes a real risk.
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as exc:
        raise PermissionDeniedError(f"invalid or expired token: {exc}") from exc
    return Principal(
        # `preferred_username` (e.g. "dev-ceo"), not Keycloak's opaque `sub`
        # UUID — every existing caller of `Principal.sub` (audit log rows,
        # RBAC checks) expects the same readable id `mint_user_jwt` used to
        # produce, and this keeps that contract intact.
        sub=data.get("preferred_username", data["sub"]),
        kind="user",
        roles=data.get("realm_access", {}).get("roles", []),
        scopes=[],
    )


def require_scopes(p: Principal, needed: list[str]) -> None:
    missing = [s for s in needed if s not in p.scopes]
    if missing:
        raise PermissionDeniedError(
            f"principal {p.sub!r} missing required scopes: {missing}",
            details={"missing": missing, "principal": p.sub},
        )


def mint_approval_token(
    *, gate: str, payload: dict[str, Any], approvers: list[str], ttl_h: int, jti: str
) -> str:
    """Called only from mcps/approvals/tokens.py after a human approves via the
    UI — never reachable from any agent scope (doc 08 §5)."""
    now = int(time.time())
    claims = {
        "jti": jti,
        "gate": gate,
        "payload_hash": canonical_payload_hash(payload),
        "approvers": approvers,
        "iss": _issuer(),
        "iat": now,
        "exp": now + ttl_h * 3600,
    }
    return jwt.encode(claims, _approval_secret(), algorithm=ALGORITHM)


async def verify_approval_token(
    token: str, gate: str, payload: dict[str, Any], *, redis: Redis
) -> ApprovalToken:
    """Signature + gate match + payload-hash match + single-use + not-expired.

    This is the entire HITL enforcement mechanism (AD-07): a tool marked 🔒
    calls this before acting. There is no prompt-level "ask permission" path
    to bypass — an agent with a stale, wrong-gate, or already-used token gets
    an `ApprovalRequiredError`, full stop.
    """
    try:
        data = jwt.decode(token, _approval_secret(), algorithms=[ALGORITHM], issuer=_issuer())
    except jwt.PyJWTError as exc:
        raise ApprovalRequiredError(f"invalid approval token: {exc}") from exc

    tok = ApprovalToken(
        jti=data["jti"],
        gate=data["gate"],
        payload_hash=data["payload_hash"],
        approvers=data.get("approvers", []),
        exp=datetime.fromtimestamp(data["exp"], tz=UTC),
    )

    if tok.gate != gate:
        raise ApprovalRequiredError(
            f"approval token is for gate {tok.gate!r}, not {gate!r}",
            details={"expected_gate": gate, "token_gate": tok.gate},
        )
    if tok.payload_hash != canonical_payload_hash(payload):
        raise ApprovalRequiredError(
            "approval token payload hash mismatch — payload changed since approval"
        )
    if tok.exp < _utcnow():
        raise ApprovalRequiredError("approval token expired")

    ttl_s = max(int((tok.exp - _utcnow()).total_seconds()), 1) + 60
    first_use = await redis.set(f"approval_used:{tok.jti}", "1", nx=True, ex=ttl_s)
    if not first_use:
        raise ApprovalRequiredError(
            "approval token already used (replay detected)", details={"jti": tok.jti}
        )
    return tok
