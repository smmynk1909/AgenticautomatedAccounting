"""Principals, service/user JWTs, and cryptographic HITL approval tokens.

Contract per doc 11 §1.2. **DEVIATIONS.md #2**: `verify_jwt` checks a local
HS256 secret instead of a Keycloak JWKS. Every other function's signature and
behavior — including `verify_approval_token`'s structural, non-bypassable
HITL enforcement (doc 08 §0, AD-07) — matches the doc contract exactly, so
swapping in Keycloak later only touches this module's key-source, never a
caller.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from typing import Any, Literal

import jwt
from pydantic import BaseModel
from redis.asyncio import Redis

from awp_shared.errors import ApprovalRequiredError, PermissionDeniedError

ALGORITHM = "HS256"


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
        data = jwt.decode(token, _service_secret(), algorithms=[ALGORITHM], issuer=_issuer())
    except jwt.PyJWTError as exc:
        raise PermissionDeniedError(f"invalid or expired token: {exc}") from exc
    return Principal(
        sub=data["sub"],
        kind=data.get("kind", "agent"),
        roles=data.get("roles", []),
        scopes=data.get("scopes", []),
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
