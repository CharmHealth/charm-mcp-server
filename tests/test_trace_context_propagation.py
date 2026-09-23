"""Inbound W3C trace context on tool spans.

Every tool span used to be a root span: nothing extracted `traceparent`, so
a client's turn span and the server work it caused were two unrelated trees
in Grafana, with no join key between them. `@with_tool_metrics()` is the one
chokepoint all 18 tools pass through, so extraction happens there.

The no-header path matters as much as the happy one. During rollout the iOS
client won't be sending context yet, and cortex/Copilot may never send it —
those calls must still work and still produce a (root) span, never an error.
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from telemetry import tool_metrics

# A syntactically valid W3C traceparent: version-traceid-spanid-flags.
PARENT_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_SPAN_ID = "00f067aa0ba902b7"
TRACEPARENT = f"00-{PARENT_TRACE_ID}-{PARENT_SPAN_ID}-01"


@pytest.fixture
def spans(monkeypatch):
    """A real tracer writing to memory, so parentage is actually observable."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tool_metrics, "tracer", provider.get_tracer("test"))
    return exporter


def _patch_headers(monkeypatch, headers):
    """Stand in for fastmcp's request-scoped header accessor."""
    import fastmcp.server.dependencies as deps

    if headers is None:
        def _raise():
            raise RuntimeError("no active HTTP request")
        monkeypatch.setattr(deps, "get_http_headers", _raise)
    else:
        monkeypatch.setattr(deps, "get_http_headers", lambda **kw: headers)


@tool_metrics.with_tool_metrics(tool_name="probeTool")
async def _probe():
    return {"ok": True}


@pytest.mark.asyncio
async def test_span_is_parented_to_the_callers_turn_span(monkeypatch, spans) -> None:
    _patch_headers(monkeypatch, {"traceparent": TRACEPARENT})

    await _probe()

    span = spans.get_finished_spans()[0]
    assert format(span.context.trace_id, "032x") == PARENT_TRACE_ID
    assert format(span.parent.span_id, "016x") == PARENT_SPAN_ID
    assert span.attributes["trace_context_propagated"] is True


@pytest.mark.asyncio
async def test_no_traceparent_still_produces_a_root_span(monkeypatch, spans) -> None:
    """Today's behaviour for every caller. Must not become an error."""
    _patch_headers(monkeypatch, {"x-user-access-token": "irrelevant"})

    result = await _probe()

    assert result == {"ok": True}
    span = spans.get_finished_spans()[0]
    assert span.parent is None
    assert span.attributes["trace_context_propagated"] is False


@pytest.mark.asyncio
async def test_malformed_traceparent_degrades_to_a_root_span(monkeypatch, spans) -> None:
    _patch_headers(monkeypatch, {"traceparent": "not-a-traceparent"})

    result = await _probe()

    assert result == {"ok": True}
    span = spans.get_finished_spans()[0]
    assert span.parent is None
    assert span.attributes["trace_context_propagated"] is False


@pytest.mark.asyncio
async def test_stdio_mode_has_no_headers_and_must_not_raise(monkeypatch, spans) -> None:
    """get_http_headers() throws outside an HTTP request. A local stdio
    client (Claude Desktop, Cursor) must not have its tool calls fail."""
    _patch_headers(monkeypatch, None)

    result = await _probe()

    assert result == {"ok": True}
    span = spans.get_finished_spans()[0]
    assert span.parent is None
    assert span.attributes["trace_context_propagated"] is False
