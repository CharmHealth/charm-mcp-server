"""A failed read is flagged, never shown as an empty list — CH-1902.

CharmHealthAPIClient returns {"error": "HTTP 503: ..."} instead of raising.
Code that went straight to `response.get("allergies", [])` turned that into
"no allergies", so a clinician could see "No known allergies" after a failed
read, or sign an encounter whose vitals never loaded.

Three shapes, depending on the tool:
- A list action whose only read failed returns a top-level "error", which the
  metrics decorator turns into a ToolError.
- A composite read (the encounter review, reviewPatientHistory, the practice
  overview) flags each failed section as <section>_unavailable and leaves the
  data out, so the sections that did load still arrive.
- A read that worked and found nothing stays [] with no flag.

The chief complaint is the one section with a fallback: when the current read
fails, the copy saved at the last signing is included, marked
clinical_notes_source="signed_copy", alongside the flag (Vibhu's call,
2026-10-31).
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from common.app_views import app_result
from tools import (
    billing,
    clinical_data,
    clinical_support,
    communication,
    core_tools,
    encounter_management,
    intake_forms,
    patient_management,
    scheduling_tools,
    task_management,
)

FAILED = {"error": "HTTP 503: Service Unavailable"}


class _FakeAPIClient:
    """Answers from a dict; endpoints in `failing` return the client's error
    dict, and ones in `raising` raise, which covers both failure paths."""

    def __init__(self, responses=None, failing=(), raising=(), fail_all=False):
        self._responses = responses or {}
        self._failing = set(failing)
        self._raising = set(raising)
        self._fail_all = fail_all

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        if endpoint in self._raising:
            raise RuntimeError("connection reset")
        if self._fail_all or endpoint in self._failing:
            return dict(FAILED)
        return self._responses.get(endpoint, {})

    async def post(self, endpoint, data=None, params=None):
        return dict(FAILED)


def _patch(monkeypatch, module, fake) -> None:
    monkeypatch.setattr(module, "CharmHealthAPIClient", lambda **kwargs: fake)


# ── Encounter review ───────────────────────────────────────────────────

def _encounter_responses(signed_copy="Cough x 3 days", current_cc="Cough x 5 days"):
    return {
        "/encounters": {"encounters": [{
            "encounter_id": "e1", "date": "2026-10-30",
            "physician_name": "Dr. Jones", "facility_id": "f1",
            "is_approved": "false", "chart_type": "SOAP",
            "chief_complaints": signed_copy,
        }]},
        "/encounters/e1": {"encounter": {"notes": {"chief_complaints": current_cc}}},
        "/facilities": {"facilities": [{"facility_id": "f1", "facility_name": "Main St"}]},
        "/patients/p1": {"patient": {"first_name": "Amy", "last_name": "Test"}},
        "/soap/encounters/e1": {"soap_encounter": {"templates": [], "entries": [], "notes": {}}},
        "/patients/p1/vitals": {"vital_entries": [{"encounter_id": "e1", "vitals": []}]},
        "/patients/p1/diagnoses": {"patient_diagnoses": [{"encounter_id": "e1", "name": "Flu"}]},
        "/patients/p1/medications": {"medications": [{"encounter_id": "e1", "trade_name": "Tamiflu"}]},
        "/patients/p1/supplements": {"supplements": [{"encounter_id": "e1", "supplement_name": "Zinc"}]},
        "/patients/p1/lab-orders": {"lab_orders": [{"encounter_id": "e1", "test_names": "CBC"}]},
    }


async def _review(monkeypatch, fake):
    _patch(monkeypatch, encounter_management, fake)
    return await encounter_management.manageEncounter(
        action="review", patient_id="p1", encounter_id="e1",
    )


SECTIONS = {
    "vitals": "/patients/p1/vitals",
    "diagnoses": "/patients/p1/diagnoses",
    "medications": "/patients/p1/medications",
    "supplements": "/patients/p1/supplements",
    "lab_orders": "/patients/p1/lab-orders",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("section", SECTIONS)
@pytest.mark.parametrize("how", ["error_dict", "raises"])
async def test_a_failed_section_is_flagged_not_empty(monkeypatch, section, how) -> None:
    endpoint = SECTIONS[section]
    fake = _FakeAPIClient(
        _encounter_responses(),
        failing=[endpoint] if how == "error_dict" else [],
        raising=[endpoint] if how == "raises" else [],
    )

    result = await _review(monkeypatch, fake)
    details = result["encounter_details"]

    assert details[f"{section}_unavailable"] is True
    assert section not in details
    # The other sections still arrive.
    for other in SECTIONS:
        if other != section:
            assert details[other], other
            assert f"{other}_unavailable" not in details
    assert result["ready_to_sign"] is False
    assert "COULD NOT BE READ" in result["guidance"]
    assert "NOT READY TO SIGN" in result["guidance"]
    assert "To sign after review" not in result["guidance"]


@pytest.mark.asyncio
async def test_a_genuinely_empty_section_stays_an_empty_list(monkeypatch) -> None:
    responses = _encounter_responses()
    responses["/patients/p1/lab-orders"] = {"lab_orders": []}
    responses["/patients/p1/vitals"] = {"vital_entries": [{"encounter_id": "other"}]}

    details = (await _review(monkeypatch, _FakeAPIClient(responses)))["encounter_details"]

    assert details["lab_orders"] == []
    assert details["vitals"] == []
    assert not [k for k in details if k.endswith("_unavailable")]


@pytest.mark.asyncio
async def test_a_complete_review_has_no_flags_and_is_ready(monkeypatch) -> None:
    result = await _review(monkeypatch, _FakeAPIClient(_encounter_responses()))
    details = result["encounter_details"]

    assert not [k for k in details if k.endswith("_unavailable")]
    assert details["clinical_notes"] == "Cough x 5 days"
    assert "clinical_notes_source" not in details
    assert result["ready_to_sign"] is True
    assert "COULD NOT BE READ" not in result["guidance"]


@pytest.mark.asyncio
async def test_a_failed_chief_complaint_read_flags_it_and_marks_the_signed_copy(monkeypatch) -> None:
    fake = _FakeAPIClient(_encounter_responses(), failing=["/encounters/e1"])

    result = await _review(monkeypatch, fake)
    details = result["encounter_details"]

    assert details["clinical_notes_unavailable"] is True
    assert details["clinical_notes"] == "Cough x 3 days"
    assert details["clinical_notes_source"] == "signed_copy"
    assert "last signing" in result["guidance"]
    assert "✓ Clinical notes documented" not in result["summary"]


@pytest.mark.asyncio
async def test_a_failed_chief_complaint_read_with_no_signed_copy_is_still_flagged(monkeypatch) -> None:
    # Never signed: the list copy is empty, so there is nothing to fall back to.
    # Without the flag this looked exactly like "no chief complaint".
    fake = _FakeAPIClient(_encounter_responses(signed_copy=""), failing=["/encounters/e1"])

    details = (await _review(monkeypatch, fake))["encounter_details"]

    assert details["clinical_notes_unavailable"] is True
    assert "clinical_notes" not in details
    assert "clinical_notes_source" not in details


@pytest.mark.asyncio
async def test_failed_facility_and_patient_reads_are_flagged(monkeypatch) -> None:
    fake = _FakeAPIClient(_encounter_responses(), failing=["/facilities", "/patients/p1"])

    details = (await _review(monkeypatch, fake))["encounter_details"]

    assert details["facility_name_unavailable"] is True
    assert "facility_name" not in details["encounter_info"]
    assert details["patient_info_unavailable"] is True


@pytest.mark.asyncio
async def test_unread_labels_do_not_stop_signing(monkeypatch) -> None:
    # Facility name and demographics are labels: the facility id and the
    # patient are known either way, and signing locks neither.
    fake = _FakeAPIClient(_encounter_responses(), failing=["/facilities", "/patients/p1"])

    result = await _review(monkeypatch, fake)

    assert result["ready_to_sign"] is True
    assert "COULD NOT BE READ" not in result["guidance"]
    assert "Could not be read: Patient demographics, Facility name. This doesn't affect signing." in result["guidance"]
    assert "To sign after review" in result["guidance"]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["/encounters/e1", "/soap/encounters/e1"])
async def test_an_unread_note_stops_signing(monkeypatch, endpoint) -> None:
    fake = _FakeAPIClient(_encounter_responses(), failing=[endpoint])

    result = await _review(monkeypatch, fake)

    assert result["ready_to_sign"] is False
    assert "NOT READY TO SIGN" in result["guidance"]


@pytest.mark.asyncio
async def test_the_minimal_documentation_warning_names_the_real_ids(monkeypatch) -> None:
    responses = _encounter_responses(signed_copy="", current_cc="")
    for endpoint in SECTIONS.values():
        responses[endpoint] = {}
    result = await _review(monkeypatch, _FakeAPIClient(responses))

    assert "minimal documentation" in result["guidance"]
    assert "encounter_id='e1'" in result["guidance"]
    assert "{encounter_id}" not in result["guidance"]


@pytest.mark.asyncio
async def test_a_failed_encounter_list_read_says_so_not_not_found(monkeypatch) -> None:
    fake = _FakeAPIClient(_encounter_responses(), failing=["/encounters"])

    with pytest.raises(ToolError) as excinfo:
        await _review(monkeypatch, fake)

    assert "Could not read" in str(excinfo.value)
    assert "not found" not in str(excinfo.value).lower()


# ── reviewPatientHistory ──────────────────────────────────────────────

HISTORY = {
    "demographics": ("/patients/p1", "demographics"),
    "medications": ("/patients/p1/medications", "current_medications"),
    "supplements": ("/patients/p1/supplements", "current_supplements"),
    "allergies": ("/patients/p1/allergies", "allergies"),
    "vitals": ("/patients/p1/vitals", "recent_vitals"),
    "diagnoses": ("/patients/p1/diagnoses", "diagnoses"),
    "encounters": ("/encounters", "recent_encounters"),
    "appointments": ("/appointments", "upcoming_appointments"),
}


def _history_responses():
    return {
        "/patients/p1": {"patient": {"patient_id": "p1", "first_name": "Amy"}},
        "/patients/p1/medications": {"medications": [{"trade_name": "Tamiflu", "is_active": True}]},
        "/patients/p1/supplements": {"supplements": [{"supplement_name": "Zinc", "status": "1"}]},
        "/patients/p1/allergies": {"allergies": [{"allergen": "Penicillin"}]},
        "/patients/p1/vitals": {"vital_entries": [{"vitals": [{"vital_name": "Weight", "vital_value": "70"}]}]},
        "/patients/p1/diagnoses": {"patient_diagnoses": [{"name": "Flu", "status": "Active"}]},
        "/encounters": {"encounters": [{"encounter_id": "e1", "date": "2026-10-30"}]},
        "/appointments": {"appointments": [{"appointment_date": "2026-11-05"}]},
    }


async def _history(monkeypatch, fake):
    _patch(monkeypatch, patient_management, fake)
    result = await patient_management.reviewPatientHistory(patient_id="p1")
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
@pytest.mark.parametrize("section", HISTORY)
async def test_a_failed_history_section_is_flagged_not_empty(monkeypatch, section) -> None:
    endpoint, data_key = HISTORY[section]
    fake = _FakeAPIClient(_history_responses(), failing=[endpoint])

    summary = await _history(monkeypatch, fake)

    assert summary[f"{section}_unavailable"] is True
    assert data_key not in summary
    assert summary["guidance"].startswith("Clinical review INCOMPLETE")
    for other, (_, other_key) in HISTORY.items():
        if other != section:
            assert summary[other_key], other_key


@pytest.mark.asyncio
async def test_failed_allergies_are_never_read_as_none(monkeypatch) -> None:
    fake = _FakeAPIClient(_history_responses(), failing=["/patients/p1/allergies"])

    summary = await _history(monkeypatch, fake)

    assert "allergies" not in summary
    assert any("do not assume none" in g for g in summary["workflow_guidance"])


@pytest.mark.asyncio
async def test_empty_history_sections_carry_no_flags(monkeypatch) -> None:
    responses = _history_responses()
    responses["/patients/p1/allergies"] = {"allergies": []}

    summary = await _history(monkeypatch, _FakeAPIClient(responses))

    assert summary["allergies"] == []
    assert not [k for k in summary if k.endswith("_unavailable")]
    assert summary["guidance"].startswith("Clinical review complete")


def test_the_summary_card_shows_an_unloaded_section_instead_of_dropping_it() -> None:
    # The serialized wire form, as test_app_views.py inspects it: a Prefab
    # component's model_dump leaves its children out.
    rendered = json.dumps(app_result({
        "patient_id": "p1",
        "demographics": {"first_name": "Amy"},
        "allergies_unavailable": True,
        "current_medications": [{"trade_name": "Tamiflu"}],
    }, "patient_history").structured_content)

    assert "Some sections could not be loaded" in rendered
    assert "Allergies: unknown, not empty" in rendered
    assert "Could not be loaded. Unknown, not none." in rendered
    assert "No clinical detail was returned" not in rendered


# ── List actions ──────────────────────────────────────────────────────

LIST_ACTIONS = [
    (clinical_data, "managePatientVitals", dict(action="list", patient_id="p1")),
    (clinical_data, "managePatientDrugs", dict(action="list", patient_id="p1", substance_type="medication")),
    (clinical_data, "managePatientDrugs", dict(action="list", patient_id="p1", substance_type="supplement")),
    (clinical_data, "managePatientAllergies", dict(action="list", patient_id="p1")),
    (clinical_data, "managePatientDiagnoses", dict(action="list", patient_id="p1")),
    (clinical_support, "managePatientNotes", dict(action="list", patient_id="p1")),
    (clinical_support, "managePatientRecalls", dict(action="list", patient_id="p1")),
    (clinical_support, "managePatientLabs", dict(action="list", patient_id="p1")),
    (clinical_support, "managePatientLabs", dict(action="list_orders", patient_id="p1")),
    (task_management, "manageTasks", dict(action="list", view="All")),
    (encounter_management, "manageEncounter", dict(action="list", patient_id="p1")),
    (billing, "manageEncounterProcedures", dict(action="list", patient_id="p1", encounter_id="e1")),
    (scheduling_tools, "manageAppointments", dict(action="list", patient_id="p1")),
    (communication, "manageMessages", dict(action="list")),
    (intake_forms, "manageIntakeForms", dict(action="list_templates")),
    (core_tools, "findPatients", dict(query="Amy")),
    *[
        (core_tools, "getPracticeInfo", dict(info_type=t))
        for t in ("facilities", "providers", "vitals", "templates", "procedure_codes")
    ],
    (core_tools, "getPracticeInfo", dict(info_type="template_details", template_ids="t1")),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module,tool,kwargs", LIST_ACTIONS,
    ids=[f"{t}-{k.get('action') or k.get('info_type') or 'search'}" for _, t, k in LIST_ACTIONS],
)
async def test_a_list_whose_read_failed_reports_a_failure(monkeypatch, module, tool, kwargs) -> None:
    _patch(monkeypatch, module, _FakeAPIClient(fail_all=True))

    with pytest.raises(ToolError):
        await getattr(module, tool)(**kwargs)


@pytest.mark.asyncio
async def test_the_practice_overview_flags_a_failed_section(monkeypatch) -> None:
    fake = _FakeAPIClient(
        {
            "/facilities": {"facilities": [{"facility_id": "f1"}]},
            "/vitals/metrics": {"vitals": [{"vital_name": "Weight"}]},
            "/templates": {"templates": []},
        },
        failing=["/members"],
    )
    _patch(monkeypatch, core_tools, fake)

    result = await core_tools.getPracticeInfo(info_type="overview")

    assert result["providers_unavailable"] is True
    assert "providers" not in result and "provider_count" not in result
    assert result["facility_count"] == 1
    assert result["templates"] == [] and "templates_unavailable" not in result
    assert "Could not be read just now: providers" in result["guidance"]


@pytest.mark.asyncio
async def test_the_vitals_list_reads_vital_entries(monkeypatch) -> None:
    # The endpoint answers under "vital_entries". Reading only "vitals"
    # reported total_count 0 with the entries sitting next to it.
    fake = _FakeAPIClient({"/patients/p1/vitals": {"vital_entries": [
        {"vital_entry_id": "v1", "entry_date": "2026-10-30",
         "vitals": [{"vital_name": "Weight", "vital_value": "70"},
                    {"vital_name": "Pulse", "vital_value": "60"}]},
    ]}})
    _patch(monkeypatch, clinical_data, fake)

    result = await clinical_data.managePatientVitals(
        action="list", patient_id="p1", vital_name_filter="weight",
    )
    data = json.loads(result.content[0].text)

    assert data["total_count"] == 1
    assert [v["vital_name"] for v in data["vitals"][0]["vitals"]] == ["Weight"]
    # The view reads vital_entries first, so it must hold the filtered list too.
    assert data["vital_entries"] == data["vitals"]


def test_a_rejected_request_is_not_told_to_retry() -> None:
    from common.utils import failed_read_result

    rejected = failed_read_result("allergies", "HTTP 404: patient not found")
    transient = failed_read_result("allergies", "HTTP 503: Service Unavailable")
    throttled = failed_read_result("allergies", "HTTP 429: Too Many Requests")
    network = failed_read_result("allergies", "Request failed: connection reset")

    assert "retrying won't help" in rejected["guidance"]
    for result in (transient, throttled, network):
        assert "Retry" in result["guidance"]
