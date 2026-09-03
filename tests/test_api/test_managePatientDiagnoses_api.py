"""Live-server API probe for managePatientDiagnoses (src/tools/clinical_data.py).

Run against the already-running MCP server (see tests/test_api/conftest.py). Each test
is the pytest form of a command run manually via scripts/mcp_test_client.py,
and is self-contained (creates its own fresh diagnosis record) so it can be
run alone via your IDE's per-test run button.

Test data: Ahmed Choi — patient_id 100010000000018023.

Note: a successful "add" response includes CharmHealth's own backend typo
("Doagnoses saved successfully.") — that's the real API's response text,
not something in this repo, so not asserted on here.
"""
from conftest import call_tool, TEST_DATA

PATIENT_ID = TEST_DATA["patient_id"]


async def _add_diagnosis() -> str:
    resp = await call_tool(
        "managePatientDiagnoses",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "diagnosis_name": "Essential hypertension",
            "diagnosis_code": "I10",
            "code_type": "ICD10",
        },
    )
    assert "error" not in resp, f"could not add a test diagnosis: {resp}"
    return resp["patient_diagnoses"][0]["patient_diagnosis_id"]


async def test_managePatientDiagnoses_list():
    # $ ... managePatientDiagnoses '{"patient_id": "100010000000018023", "action": "list"}'
    resp = await call_tool("managePatientDiagnoses", {"patient_id": PATIENT_ID, "action": "list"})
    assert "error" not in resp


async def test_managePatientDiagnoses_add():
    # $ ... managePatientDiagnoses '{"patient_id": "100010000000018023", "action": "add", \
    #       "diagnosis_name": "Essential hypertension", "diagnosis_code": "I10", "code_type": "ICD10"}'
    resp = await call_tool(
        "managePatientDiagnoses",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "diagnosis_name": "Essential hypertension",
            "diagnosis_code": "I10",
            "code_type": "ICD10",
        },
    )
    assert "error" not in resp
    assert resp.get("patient_diagnoses")


async def test_managePatientDiagnoses_update():
    # $ ... managePatientDiagnoses '{"patient_id": "100010000000018023", "action": "update", \
    #       "record_id": "<fresh patient_diagnosis_id>", "diagnosis_status": "Resolved"}'
    record_id = await _add_diagnosis()
    resp = await call_tool(
        "managePatientDiagnoses",
        {
            "patient_id": PATIENT_ID,
            "action": "update",
            "record_id": record_id,
            "diagnosis_status": "Resolved",
        },
    )
    assert "error" not in resp
    assert resp["patient_diagnoses"][0].get("status") == "Resolved"


async def test_managePatientDiagnoses_delete():
    # $ ... managePatientDiagnoses '{"patient_id": "100010000000018023", "action": "delete", "record_id": "<fresh patient_diagnosis_id>"}'
    record_id = await _add_diagnosis()
    resp = await call_tool(
        "managePatientDiagnoses",
        {"patient_id": PATIENT_ID, "action": "delete", "record_id": record_id},
    )
    assert "error" not in resp
