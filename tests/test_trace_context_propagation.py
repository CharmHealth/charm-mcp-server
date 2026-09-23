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


# ── Correlation ids (X-Turn-Id / X-Thread-Id) ──────────────────────────
#
# Contract agreed with CharmAnywhere: headers X-Turn-Id and X-Thread-Id,
# span attributes turn_id and thread_id. Bare snake_case, matching the ~16
# attributes CharmAnywhere already emits from SpanAttr in
# TelemetryConstants.swift. turn_id is a UUID per user turn; thread_id is
# the chat thread's UUID, stable across every turn in one conversation.

TURN_ID = "3f1b9c42-0a77-4f0e-9b1a-6f3c2d5e8a90"
THREAD_ID = "9c2e7a15-4b83-4d6f-8e21-77a0b4c1d3e5"


@pytest.mark.asyncio
async def test_turn_and_thread_ids_land_on_the_span(monkeypatch, spans) -> None:
    _patch_headers(monkeypatch, {"x-turn-id": TURN_ID, "x-thread-id": THREAD_ID})

    await _probe()

    span = spans.get_finished_spans()[0]
    assert span.attributes["turn_id"] == TURN_ID
    assert span.attributes["thread_id"] == THREAD_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("turn_key,thread_key", [
    ("X-Turn-Id", "X-Thread-Id"),
    ("X-TURN-ID", "X-THREAD-ID"),
    ("x-TuRn-Id", "X-tHrEaD-iD"),
])
async def test_header_casing_does_not_matter(monkeypatch, spans, turn_key, thread_key) -> None:
    """Starlette lowercases, but nothing in the contract promises that. The
    earlier lookup matched only lowercase or Title-Case, not any casing."""
    _patch_headers(monkeypatch, {turn_key: TURN_ID, thread_key: THREAD_ID})

    await _probe()

    span = spans.get_finished_spans()[0]
    assert span.attributes["turn_id"] == TURN_ID
    assert span.attributes["thread_id"] == THREAD_ID


@pytest.mark.asyncio
async def test_absent_ids_are_omitted_not_empty(monkeypatch, spans) -> None:
    """The client's connection handshake runs before any turn exists, and
    cortex/Copilot may never send these. An empty attribute would match a
    Grafana query for turn_id; an absent one correctly won't."""
    _patch_headers(monkeypatch, {"x-user-access-token": "irrelevant"})

    result = await _probe()

    assert result == {"ok": True}
    span = spans.get_finished_spans()[0]
    assert "turn_id" not in span.attributes
    assert "thread_id" not in span.attributes


@pytest.mark.asyncio
async def test_empty_header_value_is_treated_as_absent(monkeypatch, spans) -> None:
    _patch_headers(monkeypatch, {"x-turn-id": "", "x-thread-id": THREAD_ID})

    await _probe()

    span = spans.get_finished_spans()[0]
    assert "turn_id" not in span.attributes
    assert span.attributes["thread_id"] == THREAD_ID


@pytest.mark.asyncio
async def test_one_id_without_the_other_still_lands(monkeypatch, spans) -> None:
    _patch_headers(monkeypatch, {"x-thread-id": THREAD_ID})

    await _probe()

    span = spans.get_finished_spans()[0]
    assert span.attributes["thread_id"] == THREAD_ID
    assert "turn_id" not in span.attributes


@pytest.mark.asyncio
async def test_a_non_uuid_is_dropped_not_exported(monkeypatch, spans) -> None:
    """Span attributes leave the process on every call. Without a format check
    any caller could put arbitrary text — a patient's name, say — into
    exported telemetry."""
    _patch_headers(monkeypatch, {"x-turn-id": "Jane Smith DOB 1980-01-01", "x-thread-id": THREAD_ID})

    result = await _probe()

    assert result == {"ok": True}
    span = spans.get_finished_spans()[0]
    assert "turn_id" not in span.attributes
    assert span.attributes["thread_id"] == THREAD_ID


@pytest.mark.asyncio
async def test_an_oversized_value_is_dropped(monkeypatch, spans) -> None:
    _patch_headers(monkeypatch, {"x-turn-id": "x" * 5000})

    await _probe()

    span = spans.get_finished_spans()[0]
    assert "turn_id" not in span.attributes


@pytest.mark.asyncio
async def test_uppercase_uuid_is_forwarded_exactly(monkeypatch, spans) -> None:
    """Swift's uuidString is uppercase. Normalizing would break the Grafana
    join against the client's own spans."""
    upper = TURN_ID.upper()
    _patch_headers(monkeypatch, {"x-turn-id": upper})

    await _probe()

    span = spans.get_finished_spans()[0]
    assert span.attributes["turn_id"] == upper


@pytest.mark.asyncio
async def test_correlation_ids_work_alongside_traceparent(monkeypatch, spans) -> None:
    """The two mechanisms are independent — either, both, or neither."""
    _patch_headers(monkeypatch, {
        "traceparent": TRACEPARENT, "x-turn-id": TURN_ID, "x-thread-id": THREAD_ID,
    })

    await _probe()

    span = spans.get_finished_spans()[0]
    assert format(span.parent.span_id, "016x") == PARENT_SPAN_ID
    assert span.attributes["turn_id"] == TURN_ID
    assert span.attributes["trace_context_propagated"] is True


@pytest.mark.asyncio
async def test_stdio_mode_omits_correlation_ids_without_raising(monkeypatch, spans) -> None:
    _patch_headers(monkeypatch, None)

    result = await _probe()

    assert result == {"ok": True}
    span = spans.get_finished_spans()[0]
    assert "turn_id" not in span.attributes
