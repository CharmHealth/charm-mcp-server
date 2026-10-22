from fastmcp import FastMCP
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.rate_limiting import SlidingWindowRateLimitingMiddleware
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
import json
import logging
import re
from tools import *
from telemetry import telemetry
import sys
import os
from datetime import datetime, timezone
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


mcp_composite_server = FastMCP(name="CharmHealth API Assistant")


class _DropErrorText(logging.Filter):
    """Keep the error type, drop the error's text.

    A tool error's text is its error dict, and when the EHR rejected the call
    that dict carries the EHR's reply body, which can echo back the patient
    record it rejected. Both middlewares below log that text at ERROR. The
    caller still receives it; only the log line changes.

    A message in a shape this does not recognise is dropped whole, so a
    FastMCP upgrade that changes the format fails closed.
    """

    _ERROR_LINE = re.compile(r"^(Error in [^:]+: \w+)", re.DOTALL)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if record.name == "fastmcp.errors":
            match = self._ERROR_LINE.match(message)
            message = match.group(1) if match else "Error in request (text omitted)"
        else:
            try:
                fields = json.loads(message)
            except ValueError:
                fields = None
            if not isinstance(fields, dict):
                message = "Structured log message omitted"
            elif "error" in fields:
                fields["error"] = "omitted"
                message = json.dumps(fields)
        record.msg, record.args = message, ()
        return True


for _name in ("fastmcp.errors", "fastmcp.middleware.structured_logging"):
    logging.getLogger(_name).addFilter(_DropErrorText())

mcp_composite_server.add_middleware(ErrorHandlingMiddleware())

mcp_composite_server.add_middleware(SlidingWindowRateLimitingMiddleware(
    max_requests=100,
    window_minutes=1
))

mcp_composite_server.add_middleware(StructuredLoggingMiddleware())

mcp_composite_server.mount(server=core_tools_mcp)
mcp_composite_server.mount(server=patient_management_mcp)
mcp_composite_server.mount(server=scheduling_tools_mcp)
mcp_composite_server.mount(server=encounter_management_mcp)
mcp_composite_server.mount(server=clinical_data_mcp)
mcp_composite_server.mount(server=clinical_support_mcp)
mcp_composite_server.mount(server=task_management_mcp)
mcp_composite_server.mount(server=communication_mcp)
mcp_composite_server.mount(server=billing_mcp)
mcp_composite_server.mount(server=intake_forms_mcp)
mcp_composite_server.mount(server=referrals_mcp)

@mcp_composite_server.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})

@mcp_composite_server.custom_route("/metrics", methods=["GET"])
async def metrics_endpoint(request: Request) -> Response:
    body, content_type = telemetry.generate_metrics()
    return Response(content=body, media_type=content_type)


formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s: %(lineno)d - %(message)s"
)
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logging.basicConfig(level=logging.INFO if os.getenv("ENV") == "prod" else logging.DEBUG, handlers=[console_handler], force=True)
logger = logging.getLogger(__name__)

# Initialize telemetry after logging is configured so init messages are visible
telemetry.initialize()


if __name__ == "__main__":
    use_stdio = True
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == 'http':
        use_stdio = False
    if use_stdio:
        mcp_composite_server.run()
    else:
        host = os.getenv("MCPSERVER_HOST", "127.0.0.1")
        port = int(os.getenv("MCPSERVER_PORT", "8080"))
        mcp_composite_server.run(transport="http", host=host, port=port)