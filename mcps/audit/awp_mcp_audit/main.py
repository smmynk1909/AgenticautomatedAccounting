"""mcp-audit process entrypoint: `uvicorn awp_mcp_audit.main:app --host 0.0.0.0 --port 8000`."""

from __future__ import annotations

import os

from awp_mcp_base.asgi import build_asgi_app
from awp_mcp_base.uow import UnitOfWork, make_engine
from awp_shared.bus import make_redis
from awp_shared.config import validate_all
from fastapi import FastAPI

from awp_mcp_audit.server import make_audit_server

validate_all()

_engine = make_engine(os.environ["DATABASE_URL"])
_uow = UnitOfWork(_engine)
_redis = make_redis(os.environ["REDIS_URL"])

app: FastAPI = build_asgi_app(make_audit_server(_uow, _redis))
