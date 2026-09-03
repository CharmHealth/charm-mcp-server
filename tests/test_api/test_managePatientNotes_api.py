"""Live-server API probe for managePatientNotes (src/tools/clinical_support.py).

Run against the already-running MCP server (see tests/test_api/conftest.py).

Test data: Ahmed Choi — patient_id 100010000000018023.

CONFIRMED BUG (all actions): every action returns HTTP 401 with a huge HTML
login/error page body instead of JSON — the request never reaches a real
JSON API response. Reproduced on list, add, and delete (with a placeholder
record_id). This isn't data-dependent (add fails before any record exists to
list/update/delete), so it's not fixable by retrying with different data —
looks like either a wrong endpoint path or a missing OAuth scope for the
"quicknotes" feature specifically (compare: managePatientDrugs' "prescribe"
docstring already documents a similar confirmed scope gap for /drug/search).
These assertions are written for CORRECT behavior (not xfail) so they go
green the moment this is fixed.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi


async def test_managePatientNotes_list():
    # $ ... managePatientNotes '{"patient_id": "100010000000018023", "action": "list"}'
    resp = await call_tool("managePatientNotes", {"patient_id": PATIENT_ID, "action": "list"})
    assert "error" not in resp, f"quicknotes list still broken: {str(resp)[:300]}"


async def test_managePatientNotes_add():
    # $ ... managePatientNotes '{"patient_id": "100010000000018023", "action": "add", "notes": "..."}'
    resp = await call_tool(
        "managePatientNotes",
        {"patient_id": PATIENT_ID, "action": "add", "notes": "MCP API probe test note - safe to ignore"},
    )
    assert "error" not in resp, f"quicknotes add still broken: {str(resp)[:300]}"


async def test_managePatientNotes_delete():
    # $ ... managePatientNotes '{"patient_id": "100010000000018023", "action": "delete", "record_id": "<any id>"}'
    #
    # Uses a placeholder record_id since "add" can't succeed to produce a real one
    # (see test above) -- this test independently confirms delete has the same
    # 401/HTML failure, not just a "record not found" error for the fake id.
    resp = await call_tool(
        "managePatientNotes",
        {"patient_id": PATIENT_ID, "action": "delete", "record_id": "123456"},
    )
    assert "error" not in resp, f"quicknotes delete still broken: {str(resp)[:300]}"
