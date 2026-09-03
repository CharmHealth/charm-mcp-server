"""Live-server API probe for managePatientVitals (src/tools/clinical_data.py).

Run against the already-running MCP server (see tests/test_api/conftest.py). Each test
is the pytest form of a command run manually via scripts/mcp_test_client.py.

Test data: Ahmed Choi — patient_id 100010000000018023.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi


async def _add_vital() -> str:
    """Shared setup, not a test itself: add a fresh vital entry, return its id."""
    resp = await call_tool(
        "managePatientVitals",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "vital_name": "Weight",
            "vital_value": "150",
            "vital_unit": "lbs",
            "entry_date": "2026-09-01",
        },
    )
    assert "error" not in resp, f"could not add a test vital: {resp}"
    return resp["vital_entries"][0]["vital_entry_id"]


async def test_managePatientVitals_list():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py managePatientVitals \
    #     '{"patient_id": "100010000000018023", "action": "list"}'
    resp = await call_tool("managePatientVitals", {"patient_id": PATIENT_ID, "action": "list"})
    assert "error" not in resp


async def test_managePatientVitals_add():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py managePatientVitals \
    #     '{"patient_id": "100010000000018023", "action": "add", "vital_name": "Weight", \
    #       "vital_value": "150", "vital_unit": "lbs", "entry_date": "2026-09-01"}'
    resp = await call_tool(
        "managePatientVitals",
        {
            "patient_id": PATIENT_ID,
            "action": "add",
            "vital_name": "Weight",
            "vital_value": "150",
            "vital_unit": "lbs",
            "entry_date": "2026-09-01",
        },
    )
    assert "error" not in resp
    assert resp.get("vital_entries")


async def test_managePatientVitals_update():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py managePatientVitals \
    #     '{"patient_id": "100010000000018023", "action": "update", "record_id": "<fresh vital_entry_id>", \
    #       "vital_name": "Weight", "vital_value": "152", "vital_unit": "lbs"}'
    record_id = await _add_vital()
    resp = await call_tool(
        "managePatientVitals",
        {
            "patient_id": PATIENT_ID,
            "action": "update",
            "record_id": record_id,
            "vital_name": "Weight",
            "vital_value": "152",
            "vital_unit": "lbs",
        },
    )
    assert "error" not in resp
    assert resp.get("vital_entries")


async def test_managePatientVitals_delete_action_does_not_exist():
    # $ MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py managePatientVitals \
    #     '{"patient_id": "100010000000018023", "action": "delete", "record_id": "<any vital_entry_id>"}'
    #
    # CONFIRMED DOC/CODE MISMATCH: the docstring's <instructions> block documents a
    # "delete" action ("Remove incorrect vital record (requires record_id)"), but the
    # tool's `action: Literal["add", "list", "update"]` never actually includes "delete".
    # FastMCP rejects it at the protocol/schema level before the tool body ever runs.
    # This assertion documents that CURRENT (broken) behavior — it should be updated
    # (not just made to pass) once "delete" is either implemented or removed from the docs.
    record_id = await _add_vital()
    resp = await call_tool(
        "managePatientVitals",
        {"patient_id": PATIENT_ID, "action": "delete", "record_id": record_id},
    )
    assert "error" in resp
    assert "not one of" in resp["error"]
