"""Live-server API probe for managePatient (src/tools/patient_management.py).

Run against the already-running MCP server (see tests/test_api/conftest.py).

Test data: Ahmed Choi — patient_id 100010000000018023.

FIXED BUG (2026-09-02): the update_specific_details=True branch never
included record_id in the PUT payload, even though this practice requires
it — failed with HTTP 400 "Patient Record Id is mandatory. Please specify
it." Fixed by merging record_id (caller-supplied or from the existing
record) alongside first_name/last_name/gender/dob in patient_management.py.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi


async def test_managePatient_update():
    # $ ... managePatient '{"action": "update", "patient_id": "100010000000018023", \
    #       "introduction": "MCP API probe test - safe to ignore"}'
    resp = await call_tool(
        "managePatient",
        {
            "action": "update",
            "patient_id": PATIENT_ID,
            "introduction": "MCP API probe test - safe to ignore",
        },
    )
    assert "error" not in resp
    assert resp.get("patient", {}).get("record_id")
