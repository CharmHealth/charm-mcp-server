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

This suite hits a real running MCP server and writes real records (several
tools it exercises have no delete/cleanup action exposed at all, so a run
leaves permanent junk behind). To stop a bare `pytest` invocation from
accidentally connecting and creating data, every test in this directory is
skipped unless you explicitly opt in via CHARM_TEST_CONFIRM=1. When run
against CHARM_TEST_ENV=production with CHARM_TEST_CONFIRM=1, tests marked
`@pytest.mark.no_delete_available` are additionally skipped, since there is
no way to clean up the permanent record they would create in a real chart.

Start the server first, e.g.:
    uv run python src/mcp_server.py http

Then run a probe file against sandbox (the default) or production:
    CHARM_TEST_CONFIRM=1 MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run pytest tests/test_api/test_manageEncounter_api.py -v -s
    CHARM_TEST_CONFIRM=1 CHARM_TEST_ENV=production MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run pytest tests/test_api/test_manageEncounter_api.py -v -s
"""
from __future__ import annotations

import json
import os

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp/")

# Opt-in gate: this suite hits a real running MCP server and writes real,
# permanent data — a bare `pytest` from the repo root must skip cleanly
# instead of trying to connect. See pytest_collection_modifyitems below.
CHARM_TEST_CONFIRM = os.getenv("CHARM_TEST_CONFIRM", "").strip().lower() in ("1", "true", "yes")

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


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def pytest_collection_modifyitems(config, items):
    """Gate this whole suite behind CHARM_TEST_CONFIRM, and gate no-delete
    tests out of production runs even when confirmed.

    Without CHARM_TEST_CONFIRM set truthy, every item collected under this
    directory (tests/test_api) is skipped — a bare `pytest` from the repo
    root must not try to connect to MCP_SERVER_URL (default
    http://127.0.0.1:8000/mcp/) or create any real records.

    With CHARM_TEST_CONFIRM set and CHARM_TEST_ENV == "production", any item
    under this directory marked @pytest.mark.no_delete_available is
    additionally skipped: those tests create a permanent record via a tool
    with no delete/cleanup action exposed, and known server-side bugs in
    some of these tools' delete endpoints make real cleanup unsafe to
    attempt against production data.

    pytest_collection_modifyitems runs once for the whole session and
    receives every collected item, not just this directory's — so every
    branch below explicitly filters to items whose file lives under
    tests/test_api before touching them, to avoid skipping unrelated tests
    elsewhere in the repo (e.g. tests/test_billing.py) when this suite is
    collected in the same run.
    """
    this_dir_items = [
        item for item in items if str(item.path).startswith(_THIS_DIR + os.sep)
    ]

    if not CHARM_TEST_CONFIRM:
        skip_unconfirmed = pytest.mark.skip(
            reason=(
                "tests/test_api probes a real running MCP server and writes real "
                "records. Set CHARM_TEST_CONFIRM=1 to opt in explicitly."
            )
        )
        for item in this_dir_items:
            item.add_marker(skip_unconfirmed)
        return

    if CHARM_TEST_ENV == "production":
        skip_no_delete = pytest.mark.skip(
            reason=(
                "creates a permanent record via a tool with no delete/cleanup action "
                "exposed; gated out of production runs."
            )
        )
        for item in this_dir_items:
            if item.get_closest_marker("no_delete_available") is not None:
                item.add_marker(skip_no_delete)
