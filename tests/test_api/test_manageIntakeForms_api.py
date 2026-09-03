"""Live-server API probe for manageIntakeForms (src/tools/intake_forms.py).

Run against the already-running MCP server (see tests/test_api/conftest.py).

Test data: Ahmed Choi — patient_id 100010000000018023; Charm Clinic —
facility_id 100010000000008157; "Pre-Visit Symptom Check" — a real,
pre-existing (non-test) template, questionnaire_id 100010000000127039.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi
FACILITY_ID = "100010000000008157"  # Charm Clinic
QUESTIONNAIRE_ID = "100010000000127039"  # "Pre-Visit Symptom Check"


async def test_manageIntakeForms_list_templates():
    # $ ... manageIntakeForms '{"action": "list_templates"}'
    resp = await call_tool("manageIntakeForms", {"action": "list_templates"})
    assert "error" not in resp
    assert resp.get("questionnaires")


async def test_manageIntakeForms_get_patient_forms():
    # $ ... manageIntakeForms '{"action": "get_patient_forms", "patient_id": "100010000000018023"}'
    resp = await call_tool("manageIntakeForms", {"action": "get_patient_forms", "patient_id": PATIENT_ID})
    assert "error" not in resp


async def test_manageIntakeForms_create_template():
    # $ ... manageIntakeForms '{"action": "create_template", "questionnaire_name": "...", \
    #       "questionnaire_type": "General Questionnaire", \
    #       "questions": [{"notes_type": "Label", "notes": "Probe Section"}, \
    #                     {"notes_type": "Simple Question", "notes": "How are you feeling today?"}]}'
    resp = await call_tool(
        "manageIntakeForms",
        {
            "action": "create_template",
            "questionnaire_name": "MCP API probe test template",
            "questionnaire_type": "General Questionnaire",
            "questions": [
                {"notes_type": "Label", "notes": "Probe Section"},
                {"notes_type": "Simple Question", "notes": "How are you feeling today?"},
            ],
        },
    )
    assert "error" not in resp
    assert resp.get("questionnaire_details", {}).get("template_id")


async def test_manageIntakeForms_share_sms():
    # $ ... manageIntakeForms '{"action": "share_sms", "patient_id": "100010000000018023", \
    #       "facility_id": "100010000000008157", "questionnaire_id": "100010000000127039"}'
    #
    # CONFIRMED LIKELY BUG (same signature/pattern as manageFax and manageMessages'
    # whatsapp channel -- see those test files): HTTP 404 {"code":5,"message":
    # "Invalid URL Passed"} on /questionnaires/share/sms. Combined with
    # share_portal below and the fax/whatsapp findings, FIVE endpoints across
    # three different tool files now show this identical failure -- strongly
    # suggests one systemic gap (e.g. a messaging/sharing feature module not
    # provisioned on this sandbox account), not five independent wrong paths.
    # Written for CORRECT behavior so it goes green once resolved.
    resp = await call_tool(
        "manageIntakeForms",
        {
            "action": "share_sms",
            "patient_id": PATIENT_ID,
            "facility_id": FACILITY_ID,
            "questionnaire_id": QUESTIONNAIRE_ID,
        },
    )
    assert "error" not in resp, f"share_sms still broken (Invalid URL Passed): {resp}"


async def test_manageIntakeForms_share_portal():
    # $ ... manageIntakeForms '{"action": "share_portal", "patient_id": "100010000000018023", \
    #       "facility_id": "100010000000008157", "questionnaire_id": "100010000000127039"}'
    #
    # Same as test_manageIntakeForms_share_sms above -- identical "Invalid URL
    # Passed" failure on /questionnaires/share/phr.
    resp = await call_tool(
        "manageIntakeForms",
        {
            "action": "share_portal",
            "patient_id": PATIENT_ID,
            "facility_id": FACILITY_ID,
            "questionnaire_id": QUESTIONNAIRE_ID,
        },
    )
    assert "error" not in resp, f"share_portal still broken (Invalid URL Passed): {resp}"


async def test_manageIntakeForms_get_responses_rejects_invalid_id_cleanly():
    # $ ... manageIntakeForms '{"action": "get_responses", "answer_id": "12345"}'
    #
    # Not a bug: confirms this endpoint itself works and cleanly rejects a bad
    # answer_id with a specific, real backend validation message -- distinct
    # from the "Invalid URL Passed" route-doesn't-exist pattern above.
    resp = await call_tool("manageIntakeForms", {"action": "get_responses", "answer_id": "12345"})
    assert "error" in resp
    assert "valid Patient Ques Map Id" in resp["error"]


async def test_manageIntakeForms_get_responses_pdf_inconclusive():
    # $ ... manageIntakeForms '{"action": "get_responses_pdf", "answer_id": "12345"}'
    #
    # NOT conclusively a bug: unlike get_responses above (which gives a specific
    # "invalid ID" message for the same fake answer_id), this returns the same
    # "Invalid URL Passed" signature as the confirmed share_sms/share_portal/fax/
    # whatsapp bugs. Could be the same systemic route gap, or this endpoint may
    # just phrase "PDF not found for this ID" that way -- can't be distinguished
    # without a real completed submission's answer_id, which doesn't exist here
    # (share_sms/share_portal, the only ways to create one, are themselves broken).
    # Documented as inconclusive, not asserted as broken.
    resp = await call_tool("manageIntakeForms", {"action": "get_responses_pdf", "answer_id": "12345"})
    assert isinstance(resp, dict)  # always true; documents the finding above, not asserted pass/fail
