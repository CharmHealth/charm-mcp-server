"""Live-server API probe for managePatientRecalls (src/tools/clinical_support.py).

Run against the already-running MCP server (see tests/test_api/conftest.py).

Test data: Ahmed Choi — patient_id 100010000000018023; Peter Parker —
provider_id 100010000000000117; Charm Clinic — facility_id 100010000000008157.

CONFIRMED BUG (all actions, two different failure modes):
- list / delete: HTTP 401 with CharmHealth's own "Unauthorized access" HTML
  error page, not a JSON API response.
- add: reaches the real API (returns JSON, not HTML) but the backend itself
  returns HTTP 400 {"code":"6","message":"Internal Error"}.
Same conclusion as managePatientNotes: looks like a missing OAuth scope or
broken routing for the "recalls" feature specifically, not something fixable
by adjusting the request payload. These assertions target CORRECT behavior
(not xfail) so they go green the moment this is fixed.
"""
from conftest import call_tool, TEST_DATA

PATIENT_ID = TEST_DATA["patient_id"]
PROVIDER_ID = TEST_DATA["provider_id"]
FACILITY_ID = TEST_DATA["facility_id"]


async def test_managePatientRecalls_list():
    # $ ... managePatientRecalls '{"patient_id": "100010000000018023", "action": "list"}'
    resp = await call_tool("managePatientRecalls", {"patient_id": PATIENT_ID, "action": "list"})
    assert "error" not in resp, f"recalls list still broken: {str(resp)[:300]}"


async def test_managePatientRecalls_add():
    # $ ... managePatientRecalls '{"patient_id": "100010000000018023", "action": "add", "recall_type": "Annual Physical", \
    #       "notes": "MCP API probe test", "provider_id": "100010000000000117", "facility_id": "100010000000008157"}'
    resp = await call_tool(
        "managePatientRecalls",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "recall_type": "Annual Physical",
            "notes": "MCP API probe test",
            "provider_id": PROVIDER_ID,
            "facility_id": FACILITY_ID,
        },
    )
    assert "error" not in resp, f"recalls add still broken: {str(resp)[:300]}"


async def test_managePatientRecalls_delete():
    # $ ... managePatientRecalls '{"patient_id": "100010000000018023", "action": "delete", "record_id": "<any id>"}'
    #
    # Placeholder record_id, since "add" can't succeed to produce a real one
    # (see test above) -- confirms delete independently has the same failure.
    resp = await call_tool(
        "managePatientRecalls",
        {"patient_id": PATIENT_ID, "action": "delete", "record_id": "123456"},
    )
    assert "error" not in resp, f"recalls delete still broken: {str(resp)[:300]}"
