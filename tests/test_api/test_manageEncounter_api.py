"""Live-server API probe for manageEncounter (src/tools/encounter_management.py).

Run against the already-running MCP server (see tests/test_api/conftest.py for how to
start it and point MCP_SERVER_URL at it). Each test is the pytest form of a
command run manually via scripts/mcp_test_client.py, and is self-contained
(creates its own fresh encounter) so it can be run alone via your IDE's
per-test run button without depending on leftover state from another test.

Test data used throughout:
- Patient: Ahmed Choi — patient_id 100010000000018023
- Provider: Peter Parker — member_id 100010000000000117 (only sign_encounter provider in this sandbox)
- Facility: Charm Clinic — facility_id 100010000000008157

Note: manageEncounter's "sign" and "unlock" are NOT idempotent-safe against a
shared encounter_id — an earlier manual test signed encounter 100010000000128111
and then couldn't unlock it (see the bug noted in test_manageEncounter_unlock
below), leaving it permanently stuck signed. Each test here creates its own
throwaway encounter instead of reusing a fixed ID, so that stuck encounter is
simply left alone/ignored rather than fixed.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi
PROVIDER_ID = "100010000000000117"  # Peter Parker
FACILITY_ID = "100010000000008157"  # Charm Clinic
ENCOUNTER_DATE = "2026-09-01"


async def _create_encounter() -> str:
    """Shared setup, not a test itself: create a fresh throwaway encounter."""
    resp = await call_tool(
        "manageEncounter",
        {
            "patient_id": PATIENT_ID,
            "action": "create",
            "provider_id": PROVIDER_ID,
            "facility_id": FACILITY_ID,
            "encounter_date": ENCOUNTER_DATE,
        },
    )
    assert "error" not in resp, f"could not create a test encounter: {resp}"
    return resp["encounter_id"]


async def test_manageEncounter_create():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py manageEncounter \
    #     '{"patient_id": "100010000000018023", "action": "create", "provider_id": "100010000000000117", \
    #       "facility_id": "100010000000008157", "encounter_date": "2026-09-01"}'
    resp = await call_tool(
        "manageEncounter",
        {
            "patient_id": PATIENT_ID,
            "action": "create",
            "provider_id": PROVIDER_ID,
            "facility_id": FACILITY_ID,
            "encounter_date": ENCOUNTER_DATE,
        },
    )
    assert "error" not in resp
    assert resp.get("encounter_id")


async def test_manageEncounter_list():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py manageEncounter \
    #     '{"patient_id": "100010000000018023", "action": "list"}'
    resp = await call_tool("manageEncounter", {"patient_id": PATIENT_ID, "action": "list"})
    assert "error" not in resp
    assert resp.get("encounters")


async def test_manageEncounter_review():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py manageEncounter \
    #     '{"patient_id": "100010000000018023", "action": "review", "encounter_id": "<fresh encounter_id>"}'
    encounter_id = await _create_encounter()
    resp = await call_tool(
        "manageEncounter",
        {"patient_id": PATIENT_ID, "action": "review", "encounter_id": encounter_id},
    )
    assert "error" not in resp
    assert "encounter_details" in resp


async def test_manageEncounter_sign():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py manageEncounter \
    #     '{"patient_id": "100010000000018023", "action": "sign", "encounter_id": "<fresh encounter_id>"}'
    encounter_id = await _create_encounter()
    resp = await call_tool(
        "manageEncounter",
        {"patient_id": PATIENT_ID, "action": "sign", "encounter_id": encounter_id},
    )
    assert "error" not in resp
    assert resp.get("signed") is True


async def test_manageEncounter_unlock():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py manageEncounter \
    #     '{"patient_id": "100010000000018023", "action": "unlock", "encounter_id": "<fresh, freshly-signed encounter_id>", \
    #       "reason": "MCP API probe test - reverting sign test"}'
    #
    # CONFIRMED BUG (see docs/api_probe_results_sandbox.md): the "unlock" case in
    # encounter_management.py posts to "/api/ehr/v1/encounters/{id}/unlock", but
    # CharmHealthAPIClient's base_url already ends in /api/ehr/v1 and every other
    # endpoint in this file uses a bare relative path. The duplicated prefix 404s,
    # surfaced here as a generic "Unknown error". Left as a real (non-xfail)
    # assertion on purpose: this test goes green the moment the path is fixed.
    encounter_id = await _create_encounter()
    sign_resp = await call_tool(
        "manageEncounter",
        {"patient_id": PATIENT_ID, "action": "sign", "encounter_id": encounter_id},
    )
    assert sign_resp.get("signed") is True, f"prerequisite sign failed, can't test unlock: {sign_resp}"

    resp = await call_tool(
        "manageEncounter",
        {
            "patient_id": PATIENT_ID,
            "action": "unlock",
            "encounter_id": encounter_id,
            "reason": "MCP API probe test - reverting sign test",
        },
    )
    assert "error" not in resp, f"unlock still broken (see known bug note above): {resp}"
    assert resp.get("unlocked") is True
