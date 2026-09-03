"""Shared helper for live-server MCP probe tests (CH-<ticket>).

These tests call an already-running charm-mcp-server over its HTTP MCP
endpoint — the exact same way scripts/mcp_test_client.py does — so running
them costs a real HTTP call, never an LLM token. Point MCP_SERVER_URL at
whichever running instance you want to exercise; sandbox vs production is
whatever CHARMHEALTH_* the server itself was started with, not anything
these tests control.

Start the server first, e.g.:
    uv run python src/mcp_server.py http

Then run a probe file (or a single test via your IDE's run button):
    MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run pytest tests/test_manageEncounter_api.py -v -s
"""
from __future__ import annotations

import json
import os

from fastmcp import Client
from fastmcp.exceptions import ToolError

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp/")


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
