"""Dev-mode login — DEVIATIONS.md #2. Mints a session JWT for a
`config/dev_users.yaml` entry, no password. Only enabled when
`AWP_ENV=dev`; a real OIDC code-flow route replaces this at Sprint 11.
"""

from __future__ import annotations

import os
from typing import Any

from awp_shared.auth import mint_user_jwt
from awp_shared.config import get_dev_users
from awp_shared.errors import NotFoundError, ValidationError
from fastapi import APIRouter

router = APIRouter(prefix="/api/dev", tags=["dev"])


@router.post("/login")
async def dev_login(payload: dict[str, Any]) -> dict[str, str]:
    if os.environ.get("AWP_ENV") != "dev":
        raise ValidationError("dev login is only available when AWP_ENV=dev")
    user_id = payload.get("user_id")
    if not user_id:
        raise ValidationError("dev_login requires 'user_id'")
    users = {u["id"]: u for u in get_dev_users()}
    user = users.get(user_id)
    if user is None:
        raise NotFoundError(f"no such dev user: {user_id!r}")
    token = mint_user_jwt(user_id, user["roles"])
    return {"token": token}
