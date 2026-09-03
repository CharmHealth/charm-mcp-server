"""Shared helper for live-server MCP probe tests (CH-<ticket>).

These tests call an already-running charm-mcp-server over its HTTP MCP
endpoint — the exact same way scripts/mcp_test_client.py does — so running
them costs a real HTTP call, never an LLM token. Point MCP_SERVER_URL at
whichever running instance you want to exercise; sandbox vs production is
whatever CHARMHEALTH_* the server itself was started with, not anything
these tests control.

Test data (patient/provider/facility/questionnaire IDs) tracks the same
sandbox-vs-production split via CHARM_TEST_ENV — see TEST_DATA below. Set it
to match whichever environment MCP_SERVER_URL's server was actually started
against; nothing here can detect that automatically.

Start the server first, e.g.:
    uv run python src/mcp_server.py http

Then run a probe file against sandbox (the default) or production:
    MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run pytest tests/test_manageEncounter_api.py -v -s
    CHARM_TEST_ENV=production MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run pytest tests/test_manageEncounter_api.py -v -s
"""
from __future__ import annotations

import json
import os

from fastmcp import Client
from fastmcp.exceptions import ToolError

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp/")

# Test data per environment — add a key here (not to individual test files) when a
# probe needs a new shared entity id.
_TEST_DATA_BY_ENV = {
    "sandbox": {
        "patient_id": "100010000000018023",  # Ahmed Choi
        "provider_id": "100010000000000117",  # Peter Parker (only provider in this sandbox)
        "facility_id": "100010000000008157",  # Charm Clinic
        "questionnaire_id": "100010000000127039",  # "Pre-Visit Symptom Check" (real, pre-existing template)
    },
    "production": {
        "patient_id": "513000019594065",  # Amy Test patient
        "provider_id": "513000035213007",  # Sumana Ramanathan
        "facility_id": "513000030839375",  # Charm Clinic
        "questionnaire_id": "513000033416055",  # Insurance (real, pre-existing template)
    },
}

CHARM_TEST_ENV = os.getenv("CHARM_TEST_ENV", "sandbox").strip().lower()
if CHARM_TEST_ENV not in _TEST_DATA_BY_ENV:
    raise ValueError(
        f"CHARM_TEST_ENV must be one of {sorted(_TEST_DATA_BY_ENV)}, got {CHARM_TEST_ENV!r}"
    )

TEST_DATA = _TEST_DATA_BY_ENV[CHARM_TEST_ENV]


async def call_tool(tool_name: str, args: dict) -> dict:
    """Call `tool_name(**args)` on the running MCP server, return its parsed JSON.

    Equivalent to:
        MCP_SERVER_URL=... uv run scripts/mcp_test_client.py <tool_name> '<json args>'

    Normalizes both outcomes to a plain dict so every test can just check
    for an "error" key: a clean success returns the tool's response dict;
    a tool-reported failure (FastMCP raises ToolError when the tool returns
    an {"error": ...} payload) is unwrapped back into that same dict instead
    of letting the exception propagate.
    """
    async with Client(MCP_SERVER_URL) as client:
        try:
            result = await client.call_tool(tool_name, args)
        except ToolError as exc:
            message = str(exc)
            start, end = message.find("{"), message.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(message[start : end + 1])
                except json.JSONDecodeError:
                    pass
            return {"error": message}

        text = "".join(block.text for block in result.content if hasattr(block, "text"))
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}
