"""Tests for manageIntakeForms — list_templates, create_template,
get_patient_forms, share_sms, share_portal, get_responses, get_responses_pdf.

Fakes CharmHealthAPIClient so no real network/API access is needed — same
pattern as test_entity_name_fields.py / test_billing.py. create_template gets
the deepest coverage: it's the most involved validation logic in this file,
and two of its rules (is_mandatory forcing for Label/widget types, Allergies'
fixed options allow-list) were bugs/gaps found and fixed during review —
those get dedicated regression tests.
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from tools import intake_forms


class _FakeAPIClient:
    """Stands in for CharmHealthAPIClient — returns canned responses keyed
    by exact endpoint string, per HTTP method."""

    def __init__(self, get_responses=None, post_responses=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self.post_calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get[endpoint]

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data))
        return self._post[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(intake_forms, "CharmHealthAPIClient", lambda **kwargs: fake_client)


def _tool_error_body(exc_info) -> dict:
    return json.loads(str(exc_info.value))


def _valid_label(**overrides) -> dict:
    q = {"notes_type": "Label", "notes": "Section header"}
    q.update(overrides)
    return q


def _valid_question(**overrides) -> dict:
    q = {"notes_type": "Simple Question", "notes": "How are you feeling today?"}
    q.update(overrides)
    return q


# ── list_templates ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_templates_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/questionnaires": {"questionnaires": [{"questionnaire_id": 1, "name": "Intake"}]},
    })
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(action="list_templates")

    assert result["total_count"] == 1
    assert "1 questionnaire template(s)" in result["guidance"]


@pytest.mark.asyncio
async def test_list_templates_error_response_reports_failure_not_empty(monkeypatch) -> None:
    # response.get("questionnaires") is falsy on an error response too — guidance
    # must not overwrite the error with a misleading "none found" message.
    fake = _FakeAPIClient(get_responses={
        "/questionnaires": {"error": "Invalid value passed for type"},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(action="list_templates")

    assert "Failed to list questionnaire templates" in _tool_error_body(exc_info)["guidance"]


# ── get_patient_forms ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_patient_forms_filters_by_appointment(monkeypatch) -> None:
    # Real wrapper key confirmed against EntityXMLFormat.xml: "patient_questionnaires",
    # not "questionnaires" (that key belongs to /questionnaires / list_templates).
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/questionnaires": {"patient_questionnaires": [{"ques_map_id": 1, "questionnaire_id": 1}]},
    })
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(
        action="get_patient_forms", patient_id="p1", appointment_id="a1",
    )

    assert result["total_count"] == 1
    assert "tied to appointment a1" in result["guidance"]


@pytest.mark.asyncio
async def test_get_patient_forms_error_response_reports_failure_not_empty(monkeypatch) -> None:
    # response.get("patient_questionnaires") is falsy on an error response too —
    # guidance must not overwrite the error with a misleading "none found" message.
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/questionnaires": {"error": "Invalid patient_id"},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(action="get_patient_forms", patient_id="p1")

    assert "Failed to retrieve forms for this patient" in _tool_error_body(exc_info)["guidance"]


@pytest.mark.asyncio
async def test_get_patient_forms_missing_patient_id_raises_tool_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(action="get_patient_forms")

    assert _tool_error_body(exc_info)["error"] == "patient_id required for get_patient_forms"


# ── share_sms / share_portal ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_share_sms_happy_path(monkeypatch) -> None:
    """Real payload shape confirmed against
    QuestionnaireAPIHandler.shareQuestionnairesByLink: facility_id is
    required, and the template ID goes in a "questionnaires" array of
    {"questionnaire_id": ...} objects — not the flat shape this tool sent
    before (which also lacked facility_id entirely and would have failed
    every call)."""
    fake = _FakeAPIClient(post_responses={
        "/questionnaires/share/sms": {"status": "sent"},
    })
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(
        action="share_sms", patient_id="123", facility_id="9", questionnaire_id="456",
    )

    endpoint, sent_data = fake.post_calls[0]
    assert sent_data == {
        "patient_id": 123, "facility_id": 9, "questionnaires": [{"questionnaire_id": 456}],
    }
    assert "texted to the patient" in result["guidance"]


@pytest.mark.asyncio
async def test_share_sms_non_numeric_ids_return_clean_error_no_api_call(monkeypatch) -> None:
    """Regression test for the fix: a bare int() cast used to raise a raw
    ValueError on non-numeric input; now it's a clean, house-convention
    error dict, and the API is never called."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="share_sms", patient_id="not-a-number", facility_id="9", questionnaire_id="456",
        )

    assert _tool_error_body(exc_info)["error"] == "patient_id, facility_id, and questionnaire_id must be numeric"
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_share_sms_missing_ids_raises_tool_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(action="share_sms", patient_id="123")

    assert _tool_error_body(exc_info)["error"] == "patient_id, facility_id, and questionnaire_id required for share_sms"


@pytest.mark.asyncio
async def test_share_portal_happy_path(monkeypatch) -> None:
    """Same real shape as share_sms, confirmed against
    QuestionnaireAPIHandler.shareQuestionnairesToPHR."""
    fake = _FakeAPIClient(post_responses={
        "/questionnaires/share/phr": {"status": "sent"},
    })
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(
        action="share_portal", patient_id="123", facility_id="9", questionnaire_id="456",
    )

    endpoint, sent_data = fake.post_calls[0]
    assert sent_data == {
        "patient_id": 123, "facility_id": 9, "questionnaires": [{"questionnaire_id": 456}],
    }
    assert "pushed to the patient's portal" in result["guidance"]


@pytest.mark.asyncio
async def test_share_portal_non_numeric_ids_return_clean_error_no_api_call(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="share_portal", patient_id="123", facility_id="9", questionnaire_id="not-a-number",
        )

    assert _tool_error_body(exc_info)["error"] == "patient_id, facility_id, and questionnaire_id must be numeric"
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_share_portal_missing_facility_id_raises_tool_error(monkeypatch) -> None:
    """Regression test for the fix: facility_id is required by the real
    API (shareQuestionnairesToPHR throws immediately without it) but was
    entirely missing from this tool's payload before."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="share_portal", patient_id="123", questionnaire_id="456",
        )

    assert "facility_id" in _tool_error_body(exc_info)["error"]
    assert fake.post_calls == []


# ── get_responses / get_responses_pdf ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_responses_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/questionnaire/answer/a1": {"answers": []},
    })
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(action="get_responses", answer_id="a1")

    assert "Responses retrieved" in result["guidance"]


@pytest.mark.asyncio
async def test_get_responses_missing_answer_id_raises_tool_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(action="get_responses")

    assert _tool_error_body(exc_info)["error"] == "answer_id required for get_responses"


@pytest.mark.asyncio
async def test_get_responses_pdf_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/questionnaire/answer/a1/pdf": {"pdf_url": "https://example.com/a1.pdf"},
    })
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(action="get_responses_pdf", answer_id="a1")

    assert "PDF retrieved" in result["guidance"]


# ── create_template: input coercion / required fields ────────────────────


@pytest.mark.asyncio
async def test_create_template_accepts_questions_as_json_string(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 1}})
    _patch_client(monkeypatch, fake)

    questions_str = json.dumps([_valid_question()])
    result = await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="Intake Form",
        questionnaire_type="General Questionnaire", comments="notes",
        questions=questions_str,
    )

    assert "created" in result["guidance"]
    endpoint, sent_data = fake.post_calls[0]
    assert sent_data["questions"] == [_valid_question()]


@pytest.mark.asyncio
async def test_create_template_rejects_invalid_json_string_for_questions(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Intake Form",
            questionnaire_type="General Questionnaire", comments="notes",
            questions="not-json{",
        )

    assert "must be a JSON array" in _tool_error_body(exc_info)["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_template_missing_required_fields_raises_tool_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(action="create_template")

    assert "required for create_template" in _tool_error_body(exc_info)["error"]


@pytest.mark.asyncio
async def test_create_template_questionnaire_name_too_short(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="ab",
            questionnaire_type="General Questionnaire", comments="notes",
            questions=[_valid_question()],
        )

    assert "questionnaire_name" in _tool_error_body(exc_info)["guidance"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_template_invalid_questionnaire_type(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Intake Form",
            questionnaire_type="New Patient Form",  # a real type, but fixed/practice-level — not creatable via this action
            comments="notes", questions=[_valid_question()],
        )

    assert "Invalid questionnaire_type" in _tool_error_body(exc_info)["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_template_notes_type_illegal_for_questionnaire_type(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Screening Form",
            questionnaire_type="Pre-screening Form", comments="notes",
            # "Rating" is legal for Feedback Form, not Pre-screening Form.
            questions=[{"notes_type": "Rating", "notes": "Rate your experience"}],
        )

    assert "notes_type not legal" in _tool_error_body(exc_info)["error"]
    assert fake.post_calls == []


# ── create_template: is_mandatory forcing (regression) ───────────────────


@pytest.mark.asyncio
async def test_create_template_forces_is_mandatory_false_for_widget_types(monkeypatch) -> None:
    """Regression test: the docstring always claimed is_mandatory is
    forced false for Label/widget types, but no code enforced it — a
    caller-supplied true was silently forwarded as-is. Now it's actually
    overridden before the request is sent."""
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 1}})
    _patch_client(monkeypatch, fake)

    await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="Intake Form",
        questionnaire_type="General Questionnaire", comments="notes",
        questions=[{"notes_type": "Allergies", "notes": "List allergies", "is_mandatory": True}],
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data["questions"][0]["is_mandatory"] is False


@pytest.mark.asyncio
async def test_create_template_does_not_force_is_mandatory_for_normal_questions(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 1}})
    _patch_client(monkeypatch, fake)

    await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="Intake Form",
        questionnaire_type="General Questionnaire", comments="notes",
        questions=[_valid_question(is_mandatory=True)],
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data["questions"][0]["is_mandatory"] is True


# ── create_template: label_style ──────────────────────────────────────


@pytest.mark.asyncio
async def test_create_template_defaults_label_style_when_omitted(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 1}})
    _patch_client(monkeypatch, fake)

    await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="Intake Form",
        questionnaire_type="General Questionnaire", comments="notes",
        questions=[_valid_label()],
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data["questions"][0]["label_style"] == {
        "font_weight": "normal", "text_decoration": "none",
        "font_size": 14, "font_style": "normal", "text_align": "left",
    }


@pytest.mark.asyncio
async def test_create_template_coerces_stringified_font_size(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 1}})
    _patch_client(monkeypatch, fake)

    await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="Intake Form",
        questionnaire_type="General Questionnaire", comments="notes",
        questions=[_valid_label(label_style={"font_size": "16"})],
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data["questions"][0]["label_style"]["font_size"] == 16


@pytest.mark.asyncio
async def test_create_template_rejects_invalid_label_style_enum(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Intake Form",
            questionnaire_type="General Questionnaire", comments="notes",
            questions=[_valid_label(label_style={"font_weight": "extra-bold"})],
        )

    assert "invalid label_style" in _tool_error_body(exc_info)["guidance"]
    assert fake.post_calls == []


# ── create_template: Question with Options ───────────────────────────


@pytest.mark.asyncio
async def test_create_template_question_with_options_missing_options(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Intake Form",
            questionnaire_type="General Questionnaire", comments="notes",
            questions=[{"notes_type": "Question with Options", "notes": "Pick one"}],
        )

    assert "missing options" in _tool_error_body(exc_info)["guidance"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_template_question_with_options_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 1}})
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="Intake Form",
        questionnaire_type="General Questionnaire", comments="notes",
        questions=[{
            "notes_type": "Question with Options", "notes": "Preferred contact?",
            "options": [{"option": "Email"}, {"option": "Phone"}],
        }],
    )

    assert "created" in result["guidance"]


# ── create_template: Allergies fixed options allow-list (regression) ─────


@pytest.mark.asyncio
async def test_create_template_allergies_valid_options(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 1}})
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="Intake Form",
        questionnaire_type="General Questionnaire", comments="notes",
        questions=[{
            "notes_type": "Allergies", "notes": "List allergies",
            "options": [{"option": "Drug Allergy"}, {"option": "Food Allergy"}],
        }],
    )

    assert "created" in result["guidance"]


@pytest.mark.asyncio
async def test_create_template_allergies_rejects_value_outside_allow_list(monkeypatch) -> None:
    """Regression test: the real API has a fixed 3-item allow-list for
    Allergies options (Drug/Food/Environmental Allergy) — an arbitrary
    string used to pass local validation and only fail opaquely server-side."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Intake Form",
            questionnaire_type="General Questionnaire", comments="notes",
            questions=[{
                "notes_type": "Allergies", "notes": "List allergies",
                "options": [{"option": "Seasonal Allergy"}],
            }],
        )

    assert "Allergies" in _tool_error_body(exc_info)["guidance"]
    assert fake.post_calls == []


# ── create_template: Rating Scale / Rating ───────────────────────────


@pytest.mark.asyncio
async def test_create_template_rating_scale_valid(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 1}})
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="Intake Form",
        questionnaire_type="General Questionnaire", comments="notes",
        questions=[{"notes_type": "Rating Scale", "notes": "Rate your pain", "from_scale": 1, "to_scale": 5}],
    )

    assert "created" in result["guidance"]


@pytest.mark.asyncio
async def test_create_template_rating_scale_range_too_wide(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Intake Form",
            questionnaire_type="General Questionnaire", comments="notes",
            questions=[{"notes_type": "Rating Scale", "notes": "Rate your pain", "from_scale": 1, "to_scale": 20}],
        )

    assert "Rating Scale" in _tool_error_body(exc_info)["guidance"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_template_rating_missing_description(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Feedback Form",
            questionnaire_type="Feedback Form", comments="notes",
            questions=[{"notes_type": "Rating", "notes": "Rate your visit"}],
        )

    assert "missing description" in _tool_error_body(exc_info)["guidance"]
    assert fake.post_calls == []


# ── create_template: widget de-duplication + full happy path ─────────


@pytest.mark.asyncio
async def test_create_template_rejects_duplicate_widget_type(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Intake Form",
            questionnaire_type="General Questionnaire", comments="notes",
            questions=[
                {"notes_type": "Allergies", "notes": "List allergies"},
                {"notes_type": "Allergies", "notes": "List allergies again"},
            ],
        )

    assert "used more than once" in _tool_error_body(exc_info)["guidance"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_template_full_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/questionnaire": {"questionnaire_id": 42}})
    _patch_client(monkeypatch, fake)

    result = await intake_forms.manageIntakeForms.fn(
        action="create_template", questionnaire_name="New Patient Intake",
        questionnaire_type="General Questionnaire", comments="Standard intake",
        questions=[_valid_label(), _valid_question()],
    )

    endpoint, sent_data = fake.post_calls[0]
    assert endpoint == "/questionnaire"
    assert sent_data["name"] == "New Patient Intake"
    assert sent_data["type"] == "General Questionnaire"
    assert result["questionnaire_id"] == 42
    assert "list_templates" in result["guidance"]


@pytest.mark.asyncio
async def test_create_template_api_error_response(monkeypatch) -> None:
    """The real API itself rejects the request (not caught by local
    pre-flight validation) — with_tool_metrics() still flags this as
    isError=True, same as a local validation failure, but the guidance
    text is the API-failure one, not a pre-flight message."""
    fake = _FakeAPIClient(post_responses={
        "/questionnaire": {"error": "Invalid value passed for notes_type"},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await intake_forms.manageIntakeForms.fn(
            action="create_template", questionnaire_name="Intake Form",
            questionnaire_type="General Questionnaire", comments="notes",
            questions=[_valid_question()],
        )

    assert "Failed to create the questionnaire template" in _tool_error_body(exc_info)["guidance"]
