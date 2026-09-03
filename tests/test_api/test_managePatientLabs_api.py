"""Live-server API probe for managePatientLabs (src/tools/clinical_support.py).

Run against the already-running MCP server (see tests/test_api/conftest.py).

Test data: Ahmed Choi — patient_id 100010000000018023.

"order" and "get_details" are not exercised here: "order" requires real lab
catalog values (lab_id/lab_name/medical_record_id/lab_record_id) that this
tool has no lookup action to discover (a documented limitation in the
tool's own docstring, not a bug -- the practice's catalog lookup endpoints
need an OAuth scope this app's credentials don't carry). "get_details"
needs a real group_id/lab_order_id, and Ahmed Choi has zero lab results to
get one from. Both would need real values sourced outside this tool
(CharmHealth web UI) to test meaningfully.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi


async def test_managePatientLabs_list():
    # $ ... managePatientLabs '{"action": "list", "patient_id": "100010000000018023"}'
    resp = await call_tool("managePatientLabs", {"action": "list", "patient_id": PATIENT_ID})
    assert "error" not in resp
