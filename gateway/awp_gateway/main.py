"""Gateway process entrypoint: `uvicorn awp_gateway.main:app --host 0.0.0.0 --port 8000`."""

from __future__ import annotations

import os

from awp_mcp_base.uow import UnitOfWork, make_engine
from awp_shared.auth import mint_service_jwt
from awp_shared.bus import TaskBus, make_redis
from awp_shared.config import validate_all
from awp_shared.mcpc import MCP
from fastapi import FastAPI

from awp_gateway.app import create_app
from awp_gateway.deps import GatewayState

SCOPES = [
    "erp.tasks.dispatch",
    "erp.tasks.read",
    "erp.tickets.write",
    "erp.tickets.read",
    "erp.dashboard.read",
    "finance.read",
]

validate_all()

_engine = make_engine(os.environ["DATABASE_URL"])
_uow = UnitOfWork(_engine)
_redis = make_redis(os.environ["REDIS_URL"])
_bus = TaskBus(_redis)
_mcp = MCP(
    {"erp": os.environ["MCP_ERP_URL"], "finance": os.environ["MCP_FINANCE_URL"]},
    principal_jwt_provider=lambda: mint_service_jwt("gateway-service", SCOPES),
)

app: FastAPI = create_app(GatewayState(mcp=_mcp, bus=_bus, uow=_uow))
