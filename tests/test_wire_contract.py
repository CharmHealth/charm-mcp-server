"""Wire-contract tests — the guard that protects cortex and NoEHR.

charm-cortex reads a tool result by joining the *text* content blocks
(`mcp/connector.py`: `[block.text for block in result.content ...]`) and then
hands that string to `classify_widget(tool_name, result_json)`, which does
`json.loads` on it and matches on top-level keys such as "appointments" and
"patients". NoEHR's ToolResponseRegistry decodes the same JSON.

So two properties have to hold for every tool, and neither is checked by the
per-tool unit tests (which call the tool function directly and never look at
the MCP envelope):

1. The first content block is JSON text carrying the tool's data.
2. Tool names stay un-namespaced through `mount()`.

FastMCP renders a tool that returns a bare Prefab component as
`content=[TextContent(text="[Rendered Prefab UI]")]` with the component tree in
`structured_content` — which silently strips the data cortex needs. These tests
fail loudly if that ever happens, so MCP Apps work can proceed without taking
the iOS surface down with it.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

import mcp_server
from tools import billing, core_tools, patient_management, scheduling_tools


class _FakeAPIClient:
    """Canned GET responses keyed by exact endpoint — same shape as the
    fake in test_billing.py."""

    def __init__(self, get_responses=None):
        self._get = get_responses or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get[endpoint]


APPOINTMENTS = {
    "appointments": [
        {"appointment_id": "a1", "patient_name": "Stan R.", "start_time": "09:00"},
    ]
}
PATIENTS = {"patients": [{"patient_id": "p1", "full_name": "Stan R."}]}


def _content_text(result) -> str:
    return "\n".join(b.text for b in result.content if hasattr(b, "text"))


@pytest.mark.asyncio
async def test_appointments_list_reaches_cortex_as_json(monkeypatch) -> None:
    monkeypatch.setattr(
        scheduling_tools, "CharmHealthAPIClient",
        lambda **kwargs: _FakeAPIClient({"/appointments": dict(APPOINTMENTS)}),
    )

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("manageAppointments", {
            "action": "list",
            "start_date": "2026-09-03",
            "end_date_range": "2026-09-03",
            "facility_ids": "f1",
        })

    payload = json.loads(_content_text(result))
    assert "appointments" in payload, (
        "cortex's classify_widget matches the top-level 'appointments' key; "
        "without it no appointment_list widget renders on iOS"
    )
    assert payload["appointments"][0]["appointment_id"] == "a1"


@pytest.mark.asyncio
async def test_find_patients_reaches_cortex_as_json(monkeypatch) -> None:
    monkeypatch.setattr(
        core_tools, "CharmHealthAPIClient",
        lambda **kwargs: _FakeAPIClient({"/patients": dict(PATIENTS)}),
    )

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("findPatients", {"query": "Stan"})

    payload = json.loads(_content_text(result))
    assert "patients" in payload


@pytest.mark.asyncio
async def test_app_tool_keeps_json_in_content_and_component_in_structured(monkeypatch) -> None:
    """The two halves of the MCP Apps contract, asserted together.

    A tool returning a bare Prefab component would put the literal
    "[Rendered Prefab UI]" in content and the component tree in
    structured_content — data gone for cortex and NoEHR, the App view intact, and
    nothing raised. Both halves have to be checked or the regression is silent.
    """
    monkeypatch.setattr(
        scheduling_tools, "CharmHealthAPIClient",
        lambda **kwargs: _FakeAPIClient({"/appointments": dict(APPOINTMENTS)}),
    )

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("manageAppointments", {
            "action": "list",
            "start_date": "2026-09-03",
            "end_date_range": "2026-09-03",
            "facility_ids": "f1",
        })

    text = _content_text(result)
    assert "[Rendered Prefab UI]" not in text
    assert json.loads(text)["appointments"][0]["appointment_id"] == "a1"
    assert "$prefab" in result.structured_content


@pytest.mark.asyncio
async def test_patient_summary_keeps_json_in_content(monkeypatch) -> None:
    """reviewPatientHistory carries an App view too, and cortex classifies its
    compound response as the `patient_history` widget from the JSON alone."""
    monkeypatch.setattr(
        patient_management, "CharmHealthAPIClient",
        lambda **kwargs: _FakeAPIClient({
            "/patients/p1": {"patient": {"patient_id": "p1", "full_name": "Stan R.",
                                         "record_id": "123456", "gender": "Male"}},
            "/patients/p1/vitals": {"vital_entries": []},
            "/patients/p1/diagnoses": {"diagnoses": [{"name": "Insomnia"}]},
            "/patients/p1/medications": {"medications": [{"drug_name": "Sertraline"}]},
            "/patients/p1/supplements": {"supplements": []},
            "/patients/p1/allergies": {"allergies": []},
            "/encounters": {"encounters": []},
            "/appointments": {"appointments": []},
        }),
    )

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("reviewPatientHistory", {"patient_id": "p1"})

    text = _content_text(result)
    assert "[Rendered Prefab UI]" not in text
    payload = json.loads(text)
    # cortex's reviewPatientHistory branch reads these section keys directly.
    assert payload.get("diagnoses") or payload.get("demographics")
    assert "$prefab" in result.structured_content


@pytest.mark.asyncio
async def test_tools_without_an_app_return_plain_structured_data(monkeypatch) -> None:
    """managePatientBilling declares no app — cortex has no billing widget type —
    so its structured_content must stay plain data. A Prefab envelope here would
    mean someone returned a component by accident."""
    monkeypatch.setattr(
        billing, "CharmHealthAPIClient",
        lambda **kwargs: _FakeAPIClient({"/patients/p1/balance": {"total_balance_due": 0.0}}),
    )

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool(
            "managePatientBilling", {"action": "get_balance", "patient_id": "p1"}
        )

    assert "$prefab" not in (result.structured_content or {})
    assert json.loads(_content_text(result))["total_balance_due"] == 0.0


@pytest.mark.asyncio
async def test_app_tools_advertise_a_renderer_resource() -> None:
    """`app=True` stamps a placeholder that the server resolves to a hashed
    per-tool renderer URI, and mount() must not lose it."""
    async with Client(mcp_server.mcp_composite_server) as client:
        tools = {t.name: t for t in await client.list_tools()}
        uris = [str(r.uri) for r in await client.list_resources()]

        meta = tools["manageAppointments"].meta or {}
        resource_uri = (meta.get("ui") or {}).get("resourceUri")
        assert resource_uri and resource_uri.startswith("ui://prefab/tool/")
        assert resource_uri in uris

        contents = await client.read_resource(resource_uri)
        assert getattr(contents[0], "text", "")


@pytest.mark.asyncio
async def test_mounted_tool_names_are_not_namespaced() -> None:
    """Cortex's widget classifier and mutation catalog are both keyed on the
    bare tool name. FastMCP 4.x `mount()` namespaces only when asked, and
    mcp_server.py never asks — this pins that."""
    async with Client(mcp_server.mcp_composite_server) as client:
        names = {tool.name for tool in await client.list_tools()}

    for expected in ("manageAppointments", "findPatients", "reviewPatientHistory"):
        assert expected in names, f"{expected} missing or namespaced: {sorted(names)}"


# ── Failures must not be dressed as successes ─────────────────────────


@pytest.mark.asyncio
async def test_an_api_error_still_reaches_the_client_as_an_error(monkeypatch) -> None:
    """Regression: wrapping a read in app_result hid API failures.

    `@with_tool_metrics()` raises ToolError only for a *dict* carrying an
    "error" key. A ToolResult slips past that check, so a 400 from the API came
    back as a successful call with an empty appointment list and the failure
    buried in the JSON — observed live as
    `Status: success ... API calls: 1 (0 success, 1 failed)`.
    """
    class _FailingClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *exc_info): return False
        async def get(self, endpoint, params=None):
            return {"error": 'HTTP 400: {"code":2,"error_input":"facility_ids",'
                             '"message":"Invalid value passed for facility_ids"}'}

    monkeypatch.setattr(scheduling_tools, "CharmHealthAPIClient",
                        lambda **kwargs: _FailingClient())

    async with Client(mcp_server.mcp_composite_server) as client:
        with pytest.raises(Exception) as excinfo:
            await client.call_tool("manageAppointments", {
                "action": "list", "start_date": "2026-09-07",
                "end_date_range": "2026-09-13", "facility_ids": "1995529000000021081",
            })

    assert "facility_ids" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_wildcard_facility_id_is_refused_with_a_usable_message() -> None:
    """A model with no practice context guesses facility_ids="all". The API
    answers with an opaque 400, so the tool says what is wrong and how to fix it
    before spending the call."""
    async with Client(mcp_server.mcp_composite_server) as client:
        with pytest.raises(Exception) as excinfo:
            await client.call_tool("manageAppointments", {
                "action": "list", "start_date": "2026-09-07",
                "end_date_range": "2026-09-13", "facility_ids": "all",
            })

    message = str(excinfo.value)
    assert "no wildcard value" in message
    assert "getPracticeInfo" in message


# ── An empty schedule vs a wrong facility ─────────────────────────────


class _RecordingClient:
    """Serves canned responses and records which endpoints were called."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def __aenter__(self): return self
    async def __aexit__(self, *exc_info): return False

    async def get(self, endpoint, params=None):
        self.calls.append(endpoint)
        return dict(self.responses.get(endpoint, {}))


FACILITIES = {"facilities": [{"facility_id": "1995529000000021081",
                              "facility_name": "Ink Inc."}]}


async def _list_appointments(monkeypatch, facility_ids: str, responses: dict):
    client = _RecordingClient(responses)
    monkeypatch.setattr(scheduling_tools, "CharmHealthAPIClient", lambda **kwargs: client)
    async with Client(mcp_server.mcp_composite_server) as mcp:
        result = await mcp.call_tool("manageAppointments", {
            "action": "list", "start_date": "2026-09-10",
            "end_date_range": "2026-09-10", "facility_ids": facility_ids,
        })
    return json.loads(_content_text(result)), client


@pytest.mark.asyncio
async def test_empty_result_flags_a_facility_id_the_practice_does_not_have(monkeypatch) -> None:
    """The API accepts an unknown facility id and answers 200 with an empty
    list, so a quiet day and a wrong facility look identical. Observed live: a
    caller passed facility_ids="1" and reported the schedule as clear."""
    payload, client = await _list_appointments(
        monkeypatch, "1", {"/appointments": {"appointments": []}, "/facilities": FACILITIES})

    guidance = payload["guidance"]
    assert "does not match any facility" in guidance
    # Both the rejected value and the valid ones come from the request and the
    # live response — nothing about any practice is hard-coded.
    assert "facility_ids=1 " in guidance
    assert "1995529000000021081" in guidance and "Ink Inc." in guidance
    assert "/facilities" in client.calls


@pytest.mark.asyncio
async def test_a_genuinely_empty_schedule_is_not_flagged(monkeypatch) -> None:
    payload, _ = await _list_appointments(
        monkeypatch, "1995529000000021081",
        {"/appointments": {"appointments": []}, "/facilities": FACILITIES})

    assert payload["guidance"] == "No appointments found in this date range."


@pytest.mark.asyncio
async def test_a_non_empty_result_never_pays_for_the_lookup(monkeypatch) -> None:
    """The check runs only when the answer is empty, so the common path is
    unchanged and costs no extra call."""
    payload, client = await _list_appointments(
        monkeypatch, "1995529000000021081",
        {"/appointments": {"appointments": [{"appointment_id": "a1"}]},
         "/facilities": FACILITIES})

    assert "Found" in payload["guidance"]
    assert "/facilities" not in client.calls


@pytest.mark.asyncio
async def test_a_failing_facilities_lookup_leaves_the_answer_alone(monkeypatch) -> None:
    """Fails open: this only ever annotates guidance, so a lookup failure must
    never change the result."""
    payload, _ = await _list_appointments(
        monkeypatch, "1",
        {"/appointments": {"appointments": []},
         "/facilities": {"error": "HTTP 500: upstream"}})

    assert payload["guidance"] == "No appointments found in this date range."
