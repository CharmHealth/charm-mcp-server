"""
Quick manual test client for the running charm-mcp-server (HTTP mode).

No Node/npx required — uses the fastmcp Client, which is already a project
dependency.

Usage:
    # list every mounted tool
    uv run scripts/mcp_test_client.py

    # call a specific tool with JSON args
    uv run scripts/mcp_test_client.py managePatient '{"action": "search", "query": "test"}'

    # point at a different server URL
    MCP_SERVER_URL=http://127.0.0.1:8080/mcp/ uv run scripts/mcp_test_client.py
"""

import asyncio
import json
import os
import sys

from fastmcp import Client

DEFAULT_URL = "http://127.0.0.1:8080/mcp/"


async def main() -> None:
    url = os.getenv("MCP_SERVER_URL", DEFAULT_URL)

    async with Client(url) as client:
        tools = await client.list_tools()

        if len(sys.argv) == 1:
            print(f"Connected to {url}\n{len(tools)} tool(s) mounted:\n")
            for t in tools:
                first_line = (t.description or "").strip().splitlines()[0] if t.description else ""
                print(f"- {t.name}: {first_line}")
            print("\nCall one with: uv run scripts/mcp_test_client.py <tool_name> '<json_args>'")
            return

        tool_name = sys.argv[1]
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

        print(f"Calling {tool_name} with args: {args}\n")
        result = await client.call_tool(tool_name, args)

        for block in result.content:
            if hasattr(block, "text"):
                print(block.text)
            else:
                print(block)


if __name__ == "__main__":
    asyncio.run(main())
