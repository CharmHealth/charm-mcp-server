from fastmcp import FastMCP
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.rate_limiting import SlidingWindowRateLimitingMiddleware
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
import logging
from tools import *
from telemetry import telemetry
import sys
import os
from datetime import datetime, timezone
from starlette.requests import Request
from starlette.responses import JSONResponse


mcp_composite_server = FastMCP(name="CharmHealth API Assistant")

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

@mcp_composite_server.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})




formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s: %(lineno)d - %(message)s"
)
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logging.basicConfig(level=logging.INFO if os.getenv("ENV") == "prod" else logging.DEBUG, handlers=[console_handler], force=True)
logger = logging.getLogger(__name__)


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