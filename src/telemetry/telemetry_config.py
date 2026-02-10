import os
import logging
from typing import Optional
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.resources import Resource
from prometheus_client import start_http_server
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class NullMetricInstrument:
    """Base null object for metric instruments"""
    def set(self, value, attributes=None):
        pass
    
    def add(self, value, attributes=None):
        pass
    
    def record(self, value, attributes=None):
        pass

class NullTelemetry:
    """Null object implementation of TelemetryConfig that does nothing"""
    def __init__(self):
        # Initialize all metric instruments as null objects
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
    
    def get_meter(self, name: str):
        return None

class TelemetryConfig:
    def __init__(self):
        self.service_name = os.getenv("OTEL_SERVICE_NAME")
        self.service_version = os.getenv("OTEL_SERVICE_VERSION")
        self.environment = os.getenv("ENV")
        
        # OTLP traces endpoint (Grafana Alloy in-cluster or local collector)
        self.otlp_traces_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        self.otel_enabled = os.getenv("MCP_OTEL_ENABLED", "false").lower() in ("true", "1", "yes")

        # Prometheus metrics (scraped by Grafana Alloy via pod annotations)
        self.prometheus_port = int(os.getenv("PROMETHEUS_PORT", "9464"))
        self.enable_prometheus = os.getenv("ENABLE_PROMETHEUS", "false").lower() in ("true", "1", "yes")
        
        # Initialize providers
        self.tracer_provider: Optional[TracerProvider] = None
        self.meter_provider: Optional[MeterProvider] = None
        self._initialized = False
        
        # Focused metrics instruments
        self._meter = None
        self.tool_calls_counter = None
        self.tool_duration_histogram = None
        self.api_calls_counter = None
        
    def setup_tracing(self):
        """Configure OpenTelemetry tracing (pushes to Grafana Alloy or local collector)"""
        if not self.otel_enabled or not self.otlp_traces_endpoint:
            logger.info("OTEL tracing disabled (MCP_OTEL_ENABLED not set or no endpoint configured)")
            return

        resource = Resource.create({
            "service.name": self.service_name,
            "service.version": self.service_version,
            "deployment.environment": self.environment,
        })

        self.tracer_provider = TracerProvider(resource=resource)

        otlp_exporter = OTLPSpanExporter(endpoint=self.otlp_traces_endpoint)
        span_processor = BatchSpanProcessor(otlp_exporter)
        self.tracer_provider.add_span_processor(span_processor)
        trace.set_tracer_provider(self.tracer_provider)

        logger.info(f"OTLP tracing configured: {self.otlp_traces_endpoint}")
        
    def setup_metrics(self):
        """Configure OpenTelemetry metrics (exposed via Prometheus scrape endpoint)"""
        resource = Resource.create({
            "service.name": self.service_name,
            "service.version": self.service_version,
            "deployment.environment": self.environment,
        })

        metric_readers = []

        if self.enable_prometheus:
            prometheus_reader = PrometheusMetricReader()
            metric_readers.append(prometheus_reader)
            start_http_server(self.prometheus_port)
            logger.info(f"Prometheus metrics endpoint on port {self.prometheus_port}")

        self.meter_provider = MeterProvider(
            resource=resource,
            metric_readers=metric_readers
        )
        metrics.set_meter_provider(self.meter_provider)

        self._setup_metrics_instruments()
        
    def _setup_metrics_instruments(self):
        """Initialize focused metrics instruments"""
        self._meter = self.get_meter("charmhealth_mcp_tools")
        
        self.tool_calls_counter = self._meter.create_counter(
            name="mcp_tool_calls_total",
            description="Total number of MCP tool calls by tool name, client ID, and status",
            unit="1"
        )
        
        self.tool_duration_histogram = self._meter.create_histogram(
            name="mcp_tool_duration_seconds", 
            description="Duration of MCP tool calls by tool name and client ID",
            unit="s"
        )
        
        self.api_calls_counter = self._meter.create_counter(
            name="mcp_api_calls_total",
            description="Total number of API calls within tools by tool name, client ID, and status",
            unit="1"
        )
        
        self.tool_calls_gauge = self._meter.create_gauge(
            name="mcp_tool_calls_current",
            description="Current tool call status (1=call active, 0=idle)",
            unit="1"
        )
        
        self.api_calls_gauge = self._meter.create_gauge(
            name="mcp_api_calls_current", 
            description="Current API call status (1=call active, 0=idle)",
            unit="1"
        )
        
        self.tool_success_rate_gauge = self._meter.create_gauge(
            name="mcp_tool_success_rate",
            description="Success rate of tool calls (0.0-1.0)",
            unit="1"
        )
        
        self.api_latency_gauge = self._meter.create_gauge(
            name="mcp_api_latency_current",
            description="Current API call latency",
            unit="s"
        )
        
        logger.info("Focused metrics instruments with gauges initialized")
        
    def initialize(self):
        """Initialize all telemetry components"""
        if self._initialized:
            logger.info("Telemetry already initialized, skipping...")
            return
        self.setup_tracing()
        self.setup_metrics()
        self._initialized = True
        logger.info("OpenTelemetry initialization complete")
        
    def get_tracer(self, name: str):
        """Get a tracer instance"""
        return trace.get_tracer(name, self.service_version)
        
    def get_meter(self, name: str):
        """Get a meter instance"""
        return metrics.get_meter(name, self.service_version)

# Global telemetry instance
telemetry = TelemetryConfig() if os.getenv("COLLECT_METRICS", "false").lower() in ("true", "1", "yes") else NullTelemetry()