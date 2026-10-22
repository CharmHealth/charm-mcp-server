"""manageEncounter(action="list") works without a patient; nothing else does.

Omitting patient_id lists encounters across the practice, so "every unsigned
note" is one call rather than a fan-out over patients the caller already knew
about. Every other action builds a /patients/{patient_id}/... path, and a
missing id there must fail as a message about the missing argument rather
than a 404 from /patients/None/....

Driven through the real server with `fastmcp.Client`, the way
test_wire_contract.py is, so the schema (patient_id optional) is exercised
along with the function body.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from mcp.shared.exceptions import MCPError

import mcp_server
from tools import encounter_management


class _RecordingAPIClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        self.calls.append((endpoint, params or {}))
        return dict(self._responses[endpoint])


def _content_text(result) -> str:
    return "\n".join(b.text for b in result.content if hasattr(b, "text"))


@pytest.fixture
def api(monkeypatch):
    fake = _RecordingAPIClient({"/encounters": {"encounters": [
        {"encounter_id": "e1", "patient_name": "Stan R.", "date": "2026-10-01"},
        {"encounter_id": "e2", "patient_name": "Ana M.", "date": "2026-10-02"},
    ]}})
    monkeypatch.setattr(encounter_management, "CharmHealthAPIClient", lambda **kwargs: fake)
    return fake


@pytest.mark.asyncio
async def test_list_without_patient_queries_the_whole_practice(api) -> None:
    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("manageEncounter", {
            "action": "list", "filter_by": "Status.Unsigned",
        })

    assert api.calls == [("/encounters", {"filter_by": "Status.Unsigned"})]
    payload = json.loads(_content_text(result))
    assert [e["encounter_id"] for e in payload["encounters"]] == ["e1", "e2"]
    assert "across the practice" in payload["guidance"]


@pytest.mark.asyncio
async def test_list_with_patient_still_scopes_to_that_patient(api) -> None:
    async with Client(mcp_server.mcp_composite_server) as client:
        await client.call_tool("manageEncounter", {"action": "list", "patient_id": "100"})

    assert api.calls == [("/encounters", {"patient_id": 100})]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "review", "sign", "unlock", "update"])
async def test_other_actions_reject_a_missing_patient_cleanly(api, action) -> None:
    # ErrorHandlingMiddleware turns the tool's error into a protocol error, so
    # the message arrives on the exception rather than as an isError result.
    async with Client(mcp_server.mcp_composite_server) as client:
        with pytest.raises(MCPError, match=f"patient_id is required for action='{action}'"):
            await client.call_tool("manageEncounter", {"action": action, "encounter_id": "e1"})

    assert api.calls == [], "no request should be made, least of all to /patients/None/..."
