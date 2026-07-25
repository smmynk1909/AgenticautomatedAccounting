"""OTel helpers — doc 00 §7 "every task_id = trace". `opentelemetry-*` is an
optional dependency group (`awp-shared[otel]`); with `OTEL_EXPORTER_OTLP_ENDPOINT`
unset (dev default) or the packages absent, `start_span` is a harmless no-op
context manager so every call site works identically once Sprint 11 wires a
real collector — nothing here changes at that point, only `.env`.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

try:
    from opentelemetry import trace as _otel_trace

    _HAS_OTEL = True
except ImportError:  # pragma: no cover - exercised when otel extra isn't installed
    _HAS_OTEL = False


def _tracer() -> Any:
    if _HAS_OTEL:
        return _otel_trace.get_tracer("awp")
    return None


@contextlib.contextmanager
def start_span(
    name: str, *, trace_id: uuid.UUID | str | None = None, **attrs: Any
) -> Iterator[None]:
    tracer = _tracer()
    if tracer is None or not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        yield
        return
    with tracer.start_as_current_span(name) as span:
        if trace_id is not None:
            span.set_attribute("awp.trace_id", str(trace_id))
        for k, v in attrs.items():
            span.set_attribute(k, v)
        yield
