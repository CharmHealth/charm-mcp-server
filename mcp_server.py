from fastmcp import FastMCP
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.rate_limiting import SlidingWindowRateLimitingMiddleware
from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
import logging
from patient_management import patient_management_mcp
from encounter import encounter_mcp
from practice_information import practice_information_mcp
from telemetry_config import telemetry
import logging
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

mcp_composite_server.mount(server=patient_management_mcp, prefix="PatientManagement")
mcp_composite_server.mount(server=encounter_mcp, prefix="Encounter")
mcp_composite_server.mount(server=practice_information_mcp, prefix="PracticeInformation")

@mcp_composite_server.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})




formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s: %(lineno)d - %(message)s"
)
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logging.basicConfig(level=logging.DEBUG if os.getenv("ENV") == "prod" else logging.INFO, handlers=[console_handler], force=True)
logger = logging.getLogger(__name__)




if __name__ == "__main__":
    # mcp_composite_server.run(transport="http", host="127.0.0.1", port=8080)
    mcp_composite_server.run()