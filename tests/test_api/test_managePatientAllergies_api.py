"""Live-server API probe for managePatientAllergies (src/tools/clinical_data.py).

Run against the already-running MCP server (see tests/test_api/conftest.py). Each test
is the pytest form of a command run manually via scripts/mcp_test_client.py,
and is self-contained (creates its own fresh allergy record) so it can be run
alone via your IDE's per-test run button.

Test data: Ahmed Choi — patient_id 100010000000018023.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi


async def _add_allergy() -> str:
    resp = await call_tool(
        "managePatientAllergies",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "allergen": "Latex",
            "allergy_type": "Latex",
            "severity": "Mild",
            "reactions": "Skin rash",
            "allergy_date": "2026-09-02",
        },
    )
    assert "error" not in resp, f"could not add a test allergy: {resp}"
    return resp["patient_allergy"]["patient_allergy_id"]


async def test_managePatientAllergies_list():
    # $ ... managePatientAllergies '{"patient_id": "100010000000018023", "action": "list"}'
    resp = await call_tool("managePatientAllergies", {"patient_id": PATIENT_ID, "action": "list"})
    assert "error" not in resp


async def test_managePatientAllergies_add():
    # $ ... managePatientAllergies '{"patient_id": "100010000000018023", "action": "add", "allergen": "Latex", \
    #       "allergy_type": "Latex", "severity": "Mild", "reactions": "Skin rash", "allergy_date": "2026-09-02"}'
    resp = await call_tool(
        "managePatientAllergies",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "allergen": "Latex",
            "allergy_type": "Latex",
            "severity": "Mild",
            "reactions": "Skin rash",
            "allergy_date": "2026-09-02",
        },
    )
    assert "error" not in resp
    assert resp.get("patient_allergy")


async def test_managePatientAllergies_update():
    # $ ... managePatientAllergies '{"patient_id": "100010000000018023", "action": "update", "record_id": "<fresh patient_allergy_id>", \
    #       "allergen": "Latex", "allergy_type": "Latex", "severity": "Moderate", "allergy_status": "Active", \
    #       "reactions": "Skin rash and swelling", "allergy_date": "2026-09-02"}'
    record_id = await _add_allergy()
    resp = await call_tool(
        "managePatientAllergies",
        {
            "patient_id": PATIENT_ID,
            "action": "update",
            "record_id": record_id,
            "allergen": "Latex",
            "allergy_type": "Latex",
            "severity": "Moderate",
            "allergy_status": "Active",
            "reactions": "Skin rash and swelling",
            "allergy_date": "2026-09-02",
        },
    )
    assert "error" not in resp
    assert resp.get("patient_allergy")


async def test_managePatientAllergies_delete():
    # $ ... managePatientAllergies '{"patient_id": "100010000000018023", "action": "delete", "record_id": "<fresh patient_allergy_id>"}'
    record_id = await _add_allergy()
    resp = await call_tool(
        "managePatientAllergies",
        {"patient_id": PATIENT_ID, "action": "delete", "record_id": record_id},
    )
    assert "error" not in resp
