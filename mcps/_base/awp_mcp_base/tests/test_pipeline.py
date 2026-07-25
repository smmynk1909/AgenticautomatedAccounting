import pytest
from awp_shared.audit_mw import AuditEvent
from awp_shared.auth import mint_service_jwt
from awp_shared.config import get_required_scopes, load_config
from awp_shared.errors import PermissionDeniedError, ValidationError
from fakeredis.aioredis import FakeRedis

from awp_mcp_base.ctx import Ctx
from awp_mcp_base.pipeline import ToolPipeline


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def log_event(self, event: AuditEvent) -> None:
        self.events.append(event)


def _static_scopes(server: str, tool: str) -> list[str]:
    return {"log_event": ["audit.write"]}.get(tool, [])


def _pipeline(sink: _RecordingSink | None = None, redis: FakeRedis | None = None) -> ToolPipeline:
    return ToolPipeline(
        server_name="audit",
        get_required_scopes=_static_scopes,
        audit_sink=sink or _RecordingSink(),
        redis=redis or FakeRedis(decode_responses=True),
    )


@pytest.mark.asyncio
async def test_dispatch_calls_handler_and_returns_result() -> None:
    pipeline = _pipeline()
    token = mint_service_jwt("FIN-1", ["audit.write"])

    async def handler(payload: dict, ctx: Ctx) -> dict:
        return {"echo": payload, "principal": ctx.principal.sub}

    result = await pipeline.dispatch(
        "log_event", {"tool": "post_journal"}, {"Authorization": f"Bearer {token}"}, handler
    )
    assert result["principal"] == "FIN-1"
    assert result["echo"] == {"tool": "post_journal"}


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_auth_header() -> None:
    pipeline = _pipeline()

    async def handler(payload: dict, ctx: Ctx) -> dict:
        return {}

    with pytest.raises(ValidationError):
        await pipeline.dispatch("log_event", {}, {}, handler)


@pytest.mark.asyncio
async def test_dispatch_rejects_missing_scope() -> None:
    pipeline = _pipeline()
    token = mint_service_jwt("FIN-1", [])  # no scopes

    async def handler(payload: dict, ctx: Ctx) -> dict:
        return {}

    with pytest.raises(PermissionDeniedError):
        await pipeline.dispatch("log_event", {}, {"Authorization": f"Bearer {token}"}, handler)


@pytest.mark.asyncio
async def test_dispatch_is_case_insensitive_on_headers() -> None:
    # simulates a real ASGI transport, which lowercases every header name
    pipeline = _pipeline()
    token = mint_service_jwt("FIN-1", ["audit.write"])

    async def handler(payload: dict, ctx: Ctx) -> dict:
        return {"trace_id": ctx.trace_id}

    result = await pipeline.dispatch(
        "log_event", {}, {"authorization": f"Bearer {token}", "x-trace-id": "abc-123"}, handler
    )
    assert result["trace_id"] == "abc-123"


@pytest.mark.asyncio
async def test_idempotent_replay_returns_cached_result_without_recalling_handler() -> None:
    redis = FakeRedis(decode_responses=True)
    pipeline = _pipeline(redis=redis)
    token = mint_service_jwt("FIN-1", ["audit.write"])
    calls = 0

    async def handler(payload: dict, ctx: Ctx) -> dict:
        nonlocal calls
        calls += 1
        return {"n": calls}

    headers = {"Authorization": f"Bearer {token}", "X-Idempotency-Key": "task-1:step-1"}
    first = await pipeline.dispatch("log_event", {}, headers, handler)
    second = await pipeline.dispatch("log_event", {}, headers, handler)

    assert calls == 1
    assert first == second == {"n": 1}


@pytest.mark.asyncio
async def test_approval_token_is_stripped_from_payload_and_put_on_ctx() -> None:
    pipeline = _pipeline()
    token = mint_service_jwt("FIN-1", ["audit.write"])
    seen: dict = {}

    async def handler(payload: dict, ctx: Ctx) -> dict:
        seen["payload"] = payload
        seen["approval_token"] = ctx.approval_token
        return {}

    await pipeline.dispatch(
        "log_event",
        {"amount": 100, "approval_token": "tok-abc"},
        {"Authorization": f"Bearer {token}"},
        handler,
    )
    assert seen["payload"] == {"amount": 100}
    assert seen["approval_token"] == "tok-abc"


@pytest.mark.asyncio
async def test_audit_event_emitted_for_every_call() -> None:
    sink = _RecordingSink()
    pipeline = _pipeline(sink)
    token = mint_service_jwt("FIN-1", ["audit.write"])

    async def handler(payload: dict, ctx: Ctx) -> dict:
        return {"ok": True}

    await pipeline.dispatch("log_event", {}, {"Authorization": f"Bearer {token}"}, handler)
    assert len(sink.events) == 1
    assert sink.events[0].tool == "log_event"
    assert sink.events[0].ok is True


@pytest.mark.asyncio
async def test_pipeline_wired_to_real_scopes_config_enforces_audit_write() -> None:
    """Regression guard tying the pipeline to the real config/scopes.yaml."""
    load_config.cache_clear()
    pipeline = ToolPipeline(
        server_name="audit",
        get_required_scopes=get_required_scopes,
        audit_sink=_RecordingSink(),
        redis=FakeRedis(decode_responses=True),
    )
    no_scope_token = mint_service_jwt("HR-1", [])

    async def handler(payload: dict, ctx: Ctx) -> dict:
        return {}

    with pytest.raises(PermissionDeniedError):
        await pipeline.dispatch(
            "log_event", {}, {"Authorization": f"Bearer {no_scope_token}"}, handler
        )

    ok_token = mint_service_jwt("HR-1", ["audit.write"])
    result = await pipeline.dispatch(
        "log_event", {}, {"Authorization": f"Bearer {ok_token}"}, handler
    )
    assert result == {}
