import os
import logging
import tempfile
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# PROMETHEUS_MULTIPROC_DIR must be set BEFORE importing prometheus_client.
# The library checks this env var to decide between mmap file-backed storage
# (multi-worker safe) and in-memory storage (single-process only).
if os.getenv("ENABLE_PROMETHEUS", "false").lower() == "true":
    if not os.getenv("PROMETHEUS_MULTIPROC_DIR"):
        _dir = tempfile.mkdtemp(prefix="prometheus_multiproc_")
        os.environ["PROMETHEUS_MULTIPROC_DIR"] = _dir

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
from prometheus_client.multiprocess import MultiProcessCollector

logger = logging.getLogger(__name__)

class NullMetricInstrument:
    """No-op metric instrument that supports the prometheus_client .labels() API."""
    def labels(self, *args, **kwargs):
        return self

    def inc(self, amount=1):
        pass

    def set(self, value):
        pass

    def observe(self, amount):
        pass

class NullTelemetry:
    """Null object implementation of TelemetryConfig that does nothing"""
    def __init__(self):
        self.tool_calls_counter = NullMetricInstrument()
        self.tool_duration_histogram = NullMetricInstrument()
        self.api_calls_counter = NullMetricInstrument()
        self.tool_calls_gauge = NullMetricInstrument()
        self.api_calls_gauge = NullMetricInstrument()
        self.tool_success_rate_gauge = NullMetricInstrument()
        self.api_latency_gauge = NullMetricInstrument()
        self._initialized = True

    def initialize(self):
        pass

    def get_tracer(self, name: str):
        return None

    def generate_metrics(self) -> tuple[bytes, str]:
        return b"", "text/plain"

class TelemetryConfig:
    def __init__(self):
        # OTLP traces endpoint (Grafana Alloy in-cluster or local collector)
        self.otlp_traces_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        self.otel_enabled = os.getenv("MCP_OTEL_ENABLED", "false").lower() == "true"

        # Prometheus metrics (scraped via /metrics on app port)
        self.enable_prometheus = os.getenv("ENABLE_PROMETHEUS", "false").lower() == "true"

        # Initialize providers
        self.tracer_provider: Optional[TracerProvider] = None
        self._registry: Optional[CollectorRegistry] = None
        self._initialized = False

        # Metric instruments (set in _setup_metrics_instruments)
        self.tool_calls_counter = None
        self.tool_duration_histogram = None
        self.api_calls_counter = None
        self.tool_calls_gauge = None
        self.api_calls_gauge = None
        self.tool_success_rate_gauge = None
        self.api_latency_gauge = None

    def setup_tracing(self):
        """Configure OpenTelemetry tracing (pushes to Grafana Alloy or local collector)"""
        if not self.otel_enabled or not self.otlp_traces_endpoint:
            logger.info("OTEL tracing disabled (MCP_OTEL_ENABLED not set or no endpoint configured)")
            return

        resource = Resource.create({
            "service.name": "smartlink",
            "service.namespace": "charm-svcs",
            "servicegroup": "smartlink",
        })

        self.tracer_provider = TracerProvider(resource=resource)

        otlp_exporter = OTLPSpanExporter(endpoint=self.otlp_traces_endpoint)
        span_processor = BatchSpanProcessor(otlp_exporter)
        self.tracer_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(self.tracer_provider)

        logger.info(f"OTLP tracing configured: {self.otlp_traces_endpoint}")

    def setup_prometheus(self):
        """Configure native prometheus_client metrics with multiprocess support."""
        if not self.enable_prometheus:
            logger.info("Prometheus metrics disabled (ENABLE_PROMETHEUS != true)")
            return

        multiproc_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR")
        logger.info(f"Prometheus multiprocess directory: {multiproc_dir}")

        # Registry for scrape-time aggregation across workers
        self._registry = CollectorRegistry()
        MultiProcessCollector(self._registry)

        self._setup_metrics_instruments()
        logger.info("Native prometheus_client metrics initialized (multiprocess mode)")

    def _setup_metrics_instruments(self):
        """Initialize prometheus_client metric instruments."""

        # -- Counters --
        self.tool_calls_counter = Counter(
            "mcp_tool_calls_total",
            "Total number of MCP tool calls",
            ["tool_name", "client_id", "status"],
        )

        self.api_calls_counter = Counter(
            "mcp_api_calls_total",
            "Total number of API calls within tools",
            ["api_endpoint", "method", "client_id", "status"],
        )

        # -- Histogram --
        self.tool_duration_histogram = Histogram(
            "mcp_tool_duration_seconds",
            "Duration of MCP tool calls",
            ["tool_name", "client_id"],
        )

        # -- Gauges (with multiprocess modes) --
        self.tool_calls_gauge = Gauge(
            "mcp_tool_calls_current",
            "Current tool call status (1=active, 0=idle)",
            ["tool_name", "client_id"],
            multiprocess_mode="liveall",
        )

        self.api_calls_gauge = Gauge(
            "mcp_api_calls_current",
            "Current API call status (1=active, 0=idle)",
            ["api_endpoint", "method", "client_id"],
            multiprocess_mode="liveall",
        )

        self.tool_success_rate_gauge = Gauge(
            "mcp_tool_success_rate",
            "Success rate of tool calls (0.0-1.0)",
            ["tool_name", "client_id"],
            multiprocess_mode="livemostrecent",
        )

        self.api_latency_gauge = Gauge(
            "mcp_api_latency_current",
            "Current API call latency",
            ["api_endpoint", "method", "client_id"],
            multiprocess_mode="livemostrecent",
        )

        logger.info("Prometheus metric instruments initialized")

    def generate_metrics(self) -> tuple[bytes, str]:
        """Generate Prometheus metrics output for scraping.

        Uses MultiProcessCollector to aggregate across all workers.
        """
        if not self.enable_prometheus or self._registry is None:
            return b"", "text/plain"
        return generate_latest(self._registry), CONTENT_TYPE_LATEST

    def initialize(self):
        """Initialize all telemetry components"""
        if self._initialized:
            logger.info("Telemetry already initialized, skipping...")
            return
        self.setup_tracing()
        self.setup_prometheus()
        self._initialized = True
        logger.info("Telemetry initialization complete")

    def get_tracer(self, name: str):
        """Get a tracer instance"""
        return trace.get_tracer(name)

# Global telemetry instance
telemetry = TelemetryConfig() if os.getenv("COLLECT_METRICS", "false").lower() == "true" else NullTelemetry()
