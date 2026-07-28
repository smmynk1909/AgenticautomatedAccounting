"""GET /api/auth/login + GET /api/auth/callback — Sprint 11, DEVIATIONS.md
#22. Real Keycloak OIDC Authorization Code + PKCE flow for human sessions,
alongside (not yet replacing) `dev_auth.py`'s dev-mode login — see that
file's docstring and DEVIATIONS.md #22 for why both currently coexist.

The gateway never mints its own session token for a human anymore once this
flow completes: `verify_jwt` (shared/awp_shared/auth.py) validates the
Keycloak-issued access token directly, so this router's only job is running
the OAuth dance and handing that token back to the caller.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets

import httpx
from awp_shared.auth import keycloak_issuer, keycloak_realm_url
from awp_shared.errors import PermissionDeniedError, UpstreamError, ValidationError
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

_STATE_COOKIE = "oidc_state"
_VERIFIER_COOKIE = "oidc_verifier"
_COOKIE_MAX_AGE_S = 300  # just long enough to complete a login redirect round-trip


def _client_id() -> str:
    return os.environ.get("KEYCLOAK_CLIENT_ID", "awp-gateway")


def _client_secret() -> str:
    secret = os.environ.get("KEYCLOAK_CLIENT_SECRET")
    if not secret:
        raise RuntimeError("KEYCLOAK_CLIENT_SECRET not set — copy .env.example to .env")
    return secret


def _redirect_uri() -> str:
    return os.environ.get("KEYCLOAK_REDIRECT_URI", "http://localhost:8000/api/auth/callback")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@router.get("/login")
async def login() -> RedirectResponse:
    state = _b64url(secrets.token_bytes(24))
    code_verifier = _b64url(secrets.token_bytes(32))
    code_challenge = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())

    # `keycloak_issuer()`, not `keycloak_realm_url()`: this URL goes in
    # front of a real browser, which needs whatever address Keycloak's own
    # public/external hostname resolves to (DEVIATIONS.md #22) — inside
    # Docker that's `KEYCLOAK_PUBLIC_URL`, not the container-network
    # address the gateway itself uses to call Keycloak's APIs.
    authorize_url = (
        f"{keycloak_issuer()}/protocol/openid-connect/auth"
        f"?client_id={_client_id()}&response_type=code&scope=openid"
        f"&redirect_uri={_redirect_uri()}&state={state}"
        f"&code_challenge={code_challenge}&code_challenge_method=S256"
    )
    resp = RedirectResponse(authorize_url, status_code=307)
    # `secure=False`/`samesite=lax`: this dev/staging deployment serves the
    # gateway over plain HTTP (DEVIATIONS.md #2's "single trusted-developer
    # machine" scope applies here too) and Keycloak's redirect back to
    # `/api/auth/callback` is a top-level cross-site navigation, which
    # `samesite=strict` would silently drop.
    resp.set_cookie(_STATE_COOKIE, state, max_age=_COOKIE_MAX_AGE_S, httponly=True, samesite="lax")
    resp.set_cookie(
        _VERIFIER_COOKIE, code_verifier, max_age=_COOKIE_MAX_AGE_S, httponly=True, samesite="lax"
    )
    return resp


@router.get("/callback")
async def callback(request: Request, code: str, state: str) -> dict[str, str]:
    expected_state = request.cookies.get(_STATE_COOKIE)
    code_verifier = request.cookies.get(_VERIFIER_COOKIE)
    if not expected_state or not code_verifier:
        raise ValidationError("missing oidc_state/oidc_verifier cookie — login flow expired?")
    if state != expected_state:
        raise PermissionDeniedError("oidc state mismatch — possible CSRF")

    # `keycloak_realm_url()`, not `keycloak_issuer()`: this is the gateway's
    # own outbound backend call and needs a network-reachable address
    # (`host.docker.internal` inside Docker) — the resulting token's `iss`
    # still comes out as the *public* issuer regardless (DEVIATIONS.md #22,
    # live-verified), so using the public URL here would just fail to
    # connect.
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{keycloak_realm_url()}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(),
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "code_verifier": code_verifier,
            },
        )
    if resp.status_code != 200:
        raise UpstreamError(f"keycloak token exchange failed: {resp.status_code} {resp.text}")

    # NOTE (DEVIATIONS.md #22): returned as JSON, not a redirect back into
    # `web/` with the token in hand — `web/` doesn't have a route to receive
    # it yet (this Sprint 11 slice is the OIDC backend, not the SPA wiring).
    # A real integration redirects here to something like
    # `web_origin#access_token=...` for the SPA to pick up, or sets a
    # session cookie the SPA reads back via a `/api/auth/session` call.
    return {"token": resp.json()["access_token"]}
