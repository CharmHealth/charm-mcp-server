"""Live-server API probe for managePatientDrugs (src/tools/clinical_data.py).

Run against the already-running MCP server (see tests/test_api/conftest.py). Each test
is the pytest form of a command run manually via scripts/mcp_test_client.py,
and is self-contained (creates its own fresh medication/supplement/encounter)
so it can be run alone via your IDE's per-test run button.

Test data: Ahmed Choi — patient_id 100010000000018023; Peter Parker —
provider_id 100010000000000117; Charm Clinic — facility_id 100010000000008157.
"""
from conftest import call_tool, TEST_DATA

PATIENT_ID = TEST_DATA["patient_id"]
PROVIDER_ID = TEST_DATA["provider_id"]
FACILITY_ID = TEST_DATA["facility_id"]


async def _add_medication() -> str:
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "substance_type": "medication",
            "drug_name": "Cetirizine 10mg",
            "directions": "Take 1 tablet by mouth once daily",
            "check_allergies": False,
        },
    )
    assert "error" not in resp, f"could not add a test medication: {resp}"
    return resp["medications"][0]["patient_medication_id"]


async def _add_supplement() -> str:
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "substance_type": "supplement",
            "drug_name": "Vitamin C",
            "dosage": "500",  # must be a STRING despite the docstring saying integer -- see test below
        },
    )
    assert "error" not in resp, f"could not add a test supplement: {resp}"
    return resp["patient_supplements"][0]["patient_supplement_id"]


async def _create_encounter() -> str:
    resp = await call_tool(
        "manageEncounter",
        {
            "patient_id": PATIENT_ID,
            "action": "create",
            "provider_id": PROVIDER_ID,
            "facility_id": FACILITY_ID,
            "encounter_date": "2026-09-02",
        },
    )
    assert "error" not in resp, f"could not create a test encounter: {resp}"
    return resp["encounter_id"]


async def test_managePatientDrugs_list_medication():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "list", "substance_type": "medication"}'
    resp = await call_tool(
        "managePatientDrugs",
        {"patient_id": PATIENT_ID, "action": "list", "substance_type": "medication"},
    )
    assert "error" not in resp


async def test_managePatientDrugs_list_supplement():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "list", "substance_type": "supplement"}'
    resp = await call_tool(
        "managePatientDrugs",
        {"patient_id": PATIENT_ID, "action": "list", "substance_type": "supplement"},
    )
    assert "error" not in resp


async def test_managePatientDrugs_add_medication():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "add", "substance_type": "medication", \
    #       "drug_name": "Cetirizine 10mg", "directions": "Take 1 tablet by mouth once daily", "check_allergies": false}'
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "substance_type": "medication",
            "drug_name": "Cetirizine 10mg",
            "directions": "Take 1 tablet by mouth once daily",
            "check_allergies": False,
        },
    )
    assert "error" not in resp
    assert resp.get("medications")


async def test_managePatientDrugs_add_supplement():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "add", "substance_type": "supplement", \
    #       "drug_name": "Vitamin C", "dosage": "500"}'
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "substance_type": "supplement",
            "drug_name": "Vitamin C",
            "dosage": "500",
        },
    )
    assert "error" not in resp
    assert resp.get("patient_supplements")


async def test_managePatientDrugs_add_supplement_dosage_as_integer_contradicts_docstring():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "add", "substance_type": "supplement", \
    #       "drug_name": "Vitamin C", "dosage": 500}'
    #
    # CONFIRMED DOC/CODE MISMATCH: the docstring says "For supplements: Provide
    # dosage as integer (e.g., dosage=5, not dosage='5mg')", but `dosage` is typed
    # `Optional[str]` in the function signature. FastMCP's generated schema rejects
    # a real JSON integer before the tool body ever runs. Following the docstring's
    # own example fails; passing a string (see test above) is what actually works.
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "substance_type": "supplement",
            "drug_name": "Vitamin C",
            "dosage": 500,
        },
    )
    assert "error" in resp
    assert "not valid" in resp["error"]


async def test_managePatientDrugs_update_medication():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "update", "substance_type": "medication", \
    #       "record_id": "<fresh patient_medication_id>", "directions": "Take 1 tablet by mouth once daily at bedtime"}'
    record_id = await _add_medication()
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "update",
            "substance_type": "medication",
            "record_id": record_id,
            "directions": "Take 1 tablet by mouth once daily at bedtime",
        },
    )
    assert "error" not in resp
    assert resp.get("medications")


async def test_managePatientDrugs_discontinue_medication():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "discontinue", "substance_type": "medication", \
    #       "record_id": "<fresh patient_medication_id>"}'
    record_id = await _add_medication()
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "discontinue",
            "substance_type": "medication",
            "record_id": record_id,
        },
    )
    assert "error" not in resp
    assert resp["medications"][0].get("is_active") == "false"


async def test_managePatientDrugs_update_supplement():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "update", "substance_type": "supplement", \
    #       "record_id": "<fresh patient_supplement_id>", "dosage": "1000"}'
    record_id = await _add_supplement()
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "update",
            "substance_type": "supplement",
            "record_id": record_id,
            "dosage": "1000",
        },
    )
    assert "error" not in resp
    assert resp.get("patient_supplements")


async def test_managePatientDrugs_discontinue_supplement():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "discontinue", "substance_type": "supplement", \
    #       "record_id": "<fresh patient_supplement_id>"}'
    record_id = await _add_supplement()
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "discontinue",
            "substance_type": "supplement",
            "record_id": record_id,
        },
    )
    assert "error" not in resp
    assert resp["patient_supplements"][0].get("status") == "false"


async def test_managePatientDrugs_prescribe():
    # $ ... managePatientDrugs '{"patient_id": "100010000000018023", "action": "prescribe", "substance_type": "medication", \
    #       "drug_name": "Metformin 500mg", "directions": "Take 1 tablet by mouth twice daily with meals", \
    #       "encounter_id": "<fresh encounter_id>", "check_allergies": false}'
    encounter_id = await _create_encounter()
    resp = await call_tool(
        "managePatientDrugs",
        {
            "patient_id": PATIENT_ID,
            "action": "prescribe",
            "substance_type": "medication",
            "drug_name": "Metformin 500mg",
            "directions": "Take 1 tablet by mouth twice daily with meals",
            "encounter_id": encounter_id,
            "check_allergies": False,
        },
    )
    assert "error" not in resp
    assert resp.get("medications")
