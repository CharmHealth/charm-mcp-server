import functools
import json
import time
import logging
from typing import Dict, Any, Callable, Optional
from fastmcp.exceptions import ToolError
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from opentelemetry.propagate import extract
from .telemetry_config import telemetry
import contextvars

logger = logging.getLogger(__name__)

# Context variable to track current client_id and API call count
current_client_id: contextvars.ContextVar[str] = contextvars.ContextVar('client_id', default='unknown')
api_call_count: contextvars.ContextVar[int] = contextvars.ContextVar('api_call_count', default=0)
successful_api_calls: contextvars.ContextVar[int] = contextvars.ContextVar('successful_api_calls', default=0)

# Track total tool calls and successes for success rate calculation
total_tool_calls: contextvars.ContextVar[int] = contextvars.ContextVar('total_tool_calls', default=0)
successful_tool_calls: contextvars.ContextVar[int] = contextvars.ContextVar('successful_tool_calls', default=0)

# Tracer instance — returns a no-op tracer when no TracerProvider is configured
tracer = trace.get_tracer("charm-mcp-server")


def _inbound_trace_context():
    """The caller's W3C trace context, or None when there isn't one.

    A tool span is only useful for correlation if it hangs off the span the
    caller already opened for the user's turn. Without this every span is a
    root and Grafana shows two unrelated trees for one action.

    Returns None rather than an empty Context on purpose. Passing an empty
    Context explicitly would still produce a root span, but returning None
    lets the caller omit the argument entirely and keep OpenTelemetry's own
    ambient-context behaviour, which is what every caller gets today.

    Never raises. get_http_headers() throws outside an HTTP request (stdio
    mode, background tasks), a malformed traceparent makes extract() return
    a context with no valid span, and neither is a reason to fail a clinical
    tool call — both degrade to an unparented span.
    """
    try:
        from fastmcp.server.dependencies import get_http_headers

        # traceparent/tracestate are not on get_http_headers()'s exclusion
        # list (authorization, cookie and the proxy headers are), so no
        # include= is needed here.
        ctx = extract(dict(get_http_headers()))
    except Exception:
        logger.debug("No inbound trace context available", exc_info=True)
        return None

    if trace.get_current_span(ctx).get_span_context().is_valid:
        return ctx
    return None

def with_tool_metrics(tool_name: Optional[str] = None):
    """
    Decorator that tracks metrics and creates trace spans for MCP tool calls.

    Metrics (via prometheus_client):
    - Tool call counter, duration histogram, success rate gauge
    - Active tool call gauge (1 while running, 0 when done)

    Traces (via OpenTelemetry):
    - One span per tool call with tool_name, client_id, and status attributes
    - Exception recording on errors

    Args:
        tool_name: Override the tool name (defaults to function name)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            actual_tool_name = tool_name or func.__name__

            start_time = time.time()

            # Reset API call counters for this tool execution
            api_call_count.set(0)
            successful_api_calls.set(0)

            initial_client_id = current_client_id.get('unknown')
            client_id = initial_client_id

            # Set tool call gauge to active
            telemetry.tool_calls_gauge.labels(
                tool_name=actual_tool_name,
                client_id=client_id,
            ).set(1)

            # Create a trace span for this tool call, parented to the caller's
            # turn span when it sent W3C trace context (see _inbound_trace_context).
            inbound_ctx = _inbound_trace_context()
            span_kwargs = {"context": inbound_ctx} if inbound_ctx is not None else {}
            with tracer.start_as_current_span(actual_tool_name, **span_kwargs) as span:
                span.set_attribute("tool_name", actual_tool_name)
                span.set_attribute("client_id", client_id)
                # "Did the header arrive?" is the first question when spans
                # aren't nesting in Grafana — answer it from the span itself
                # rather than by guessing at the client.
                span.set_attribute("trace_context_propagated", inbound_ctx is not None)

                try:
                    result = await func(*args, **kwargs)

                    is_success = _is_successful_response(result)
                    status = "success" if is_success else "failure"

                    # Update client_id in case it was set during execution
                    client_id = current_client_id.get('unknown')

                    span.set_attribute("status", status)

                    _record_tool_completion_metrics(actual_tool_name, client_id, start_time, status, is_success)

                except Exception as e:
                    client_id = current_client_id.get('unknown')

                    span.set_attribute("status", "error")
                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR, str(e))

                    _record_tool_completion_metrics(actual_tool_name, client_id, start_time, "error", False)
                    logger.error(f"Tool {actual_tool_name} failed with exception: {e}")
                    raise
                else:
                    # J13/CH-695: isError flag
                    if isinstance(result, dict) and "error" in result:
                        raise ToolError(json.dumps(result, indent=2))
                    return result
                finally:
                    # Clear the initial gauge entry if client_id changed mid-call
                    if client_id != initial_client_id:
                        telemetry.tool_calls_gauge.labels(
                            tool_name=actual_tool_name,
                            client_id=initial_client_id,
                        ).set(0)
                    # Set tool call gauge to idle
                    telemetry.tool_calls_gauge.labels(
                        tool_name=actual_tool_name,
                        client_id=client_id,
                    ).set(0)

        return wrapper
    return decorator

def _is_successful_response(response: Dict[str, Any]) -> bool:
    """Determine if a tool response indicates success"""
    if not isinstance(response, dict):
        return False

    if "error" in response:
        return False

    if "code" in response:
        code = response.get("code", "")
        if isinstance(code, str) and "error" in code.lower():
            return False
        if isinstance(code, int) and code >= 400:
            return False

    message = response.get("message", "")
    if isinstance(message, str) and any(error_word in message.lower() for error_word in ["error", "failed", "failure"]):
        return False

    return True

def _record_tool_completion_metrics(tool_name: str, client_id: str, start_time: float, status: str, is_success: bool):
    """Record metrics when a tool completes"""
    try:
        duration = time.time() - start_time

        if telemetry.tool_calls_counter is None:
            return

        # Counter: total tool calls
        telemetry.tool_calls_counter.labels(
            tool_name=tool_name,
            client_id=client_id,
            status=status,
        ).inc()

        # Histogram: tool duration
        telemetry.tool_duration_histogram.labels(
            tool_name=tool_name,
            client_id=client_id,
        ).observe(duration)

        # Update success rate tracking
        current_total = total_tool_calls.get(0)
        current_successful = successful_tool_calls.get(0)

        total_tool_calls.set(current_total + 1)
        if is_success:
            successful_tool_calls.set(current_successful + 1)
            current_successful += 1

        # Success rate gauge
        if (current_total + 1) > 0:
            success_rate = current_successful / (current_total + 1)
            telemetry.tool_success_rate_gauge.labels(
                tool_name=tool_name,
                client_id=client_id,
            ).set(success_rate)

        # Log completion
        total_api_calls = api_call_count.get(0)
        successful_calls = successful_api_calls.get(0)
        failed_calls = total_api_calls - successful_calls

        logger.info(
            f"Tool '{tool_name}' completed - "
            f"Status: {status}, Duration: {duration:.3f}s, "
            f"API calls: {total_api_calls} ({successful_calls} success, {failed_calls} failed), "
            f"Client: {client_id}, Success rate: {current_successful / (current_total + 1):.3f}"
        )

    except Exception as e:
        logger.error(f"Failed to record tool metrics: {e}")

def record_api_call(client_id: str, success: bool, api_endpoint: str, method: str, duration: float):
    """
    Record an individual API call within a tool.
    Call this from the API client when making requests.
    """
    try:
        current_client_id.set(client_id)
        current_count = api_call_count.get(0)
        api_call_count.set(current_count + 1)

        if success:
            current_successful = successful_api_calls.get(0)
            successful_api_calls.set(current_successful + 1)

        # Counter: total API calls
        if telemetry.api_calls_counter:
            telemetry.api_calls_counter.labels(
                api_endpoint=api_endpoint,
                method=method,
                client_id=client_id,
                status="success" if success else "failure",
            ).inc()

        # Gauge: latest API latency
        if telemetry.api_latency_gauge:
            telemetry.api_latency_gauge.labels(
                api_endpoint=api_endpoint,
                method=method,
                client_id=client_id,
            ).set(duration)

        logger.info(f"API call recorded: endpoint={api_endpoint}, method={method}, client={client_id}, success={success}, duration={duration:.3f}s")

    except Exception as e:
        logger.error(f"Failed to record API call metric: {e}")

def start_api_call(client_id: str, api_endpoint: str, method: str):
    """Mark the start of an API call (sets gauge to active)"""
    try:
        if telemetry.api_calls_gauge:
            telemetry.api_calls_gauge.labels(
                api_endpoint=api_endpoint,
                method=method,
                client_id=client_id,
            ).set(1)
    except Exception as e:
        logger.error(f"Failed to set API call gauge: {e}")

def end_api_call(client_id: str, api_endpoint: str, method: str, duration: float = 0.0, success: bool = True):
    """Mark the end of an API call (sets gauge to idle)"""
    try:
        if telemetry.api_calls_gauge:
            telemetry.api_calls_gauge.labels(
                api_endpoint=api_endpoint,
                method=method,
                client_id=client_id,
            ).set(0)
    except Exception as e:
        logger.error(f"Failed to unset API call gauge: {e}")

def set_client_context(client_id: str):
    """Set the client ID in context for the current execution"""
    current_client_id.set(client_id)
