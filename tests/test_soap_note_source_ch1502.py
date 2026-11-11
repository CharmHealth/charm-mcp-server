"""Tests for manageEncounter(action="review")'s soap_entries/soap_notes — CH-1502.

Response contract agreed with CH-1368 (cortex half, Vibhu): two new keys in
encounter_details, soap_entries (list) and soap_notes (dict), built from the
same /soap/encounters/{id} read that already supplies attached_templates.
A failed read must set soap_note_unavailable and omit both keys — same
invariant as attached_templates_unavailable, because cortex reads "no note"
and "unknown" differently (unknown -> not evaluated -> action goes through;
empty note -> evidence nothing was documented).

This ticket also removes the date-matched medication fallback in the same
review case (the fallback doesn't carry a real encounter_id, so it can't
count as guardrail evidence per the CH-1352 design doc).

Fakes CharmHealthAPIClient — same pattern as test_attached_templates_ch416.py.
"""

from __future__ import annotations

import pytest

from tools import encounter_management


class _FakeAPIClient:
    def __init__(self, get_responses=None, errors=None):
        self._get = get_responses or {}
        self._errors = errors or {}
        self.get_calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        self.get_calls.append(endpoint)
        if endpoint in self._errors:
            raise self._errors[endpoint]
        return self._get.get(endpoint, {})


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(
        encounter_management, "CharmHealthAPIClient", lambda **kwargs: fake_client
    )


def _base_responses(soap=None, encounter_date="2026-09-21", medications=None):
    responses = {
        "/encounters": {"encounters": [{
            "encounter_id": "e1", "date": encounter_date,
            "physician_name": "Dr. Jones", "facility_id": "f1",
            "visit_name": "New Patient Visit", "is_approved": "false",
            "chart_type": "SOAP",
        }]},
        "/patients/p1": {"patient": {"first_name": "Amy", "last_name": "Test"}},
        # Vitals/diagnoses/medications/supplements/lab-orders/clinical_notes
        # all now come from this one call (confirmed against
        # ChartsAPIHandler.fetchChartNoteDetails) instead of five separate
        # /patients/{id}/<field> fetches — see the "medication date-fallback
        # removal" tests below for why trusting this response wholesale is
        # safe: the backend already scopes it by a real encounter_id join.
        "/encounters/e1": {"encounter": {"medications": medications or []}},
    }
    if soap is not None:
        responses["/soap/encounters/e1"] = soap
    return responses


async def _review(monkeypatch, fake):
    _patch_client(monkeypatch, fake)
    return await encounter_management.manageEncounter(
        action="review", patient_id="p1", encounter_id="e1",
    )


LIVE_ENTRY = {
    "entry_id": 100234000001234567,
    "entry_name": "Mood",
    "entry_type": "Checkbox",
    "entry_chart_section": "Symptoms",
    "answer": "Check2^^>>Subcheck2",
    "is_entry_deleted": "false",
    "is_answer_deleted": "false",
}

NOTES = {
    "assessment_notes": "<div>Adjustment disorder, improving.</div>",
    "history_of_present_illness": "<div>Reports low mood since job loss in June.</div>",
    "physical_examination": None,
    "past_medical_history": "",
}


@pytest.mark.asyncio
async def test_review_surfaces_soap_entries_and_notes(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"templates": [], "entries": [LIVE_ENTRY], "notes": NOTES},
    }))

    result = await _review(monkeypatch, fake)

    details = result["encounter_details"]
    assert details["soap_entries"] == [{
        "entry_id": "100234000001234567",
        "entry_name": "Mood",
        "entry_type": "Checkbox",
        "entry_chart_section": "Symptoms",
        "answer": "Check2^^>>Subcheck2",
    }]
    assert details["soap_notes"] == {
        "assessment_notes": "<div>Adjustment disorder, improving.</div>",
        "history_of_present_illness": "<div>Reports low mood since job loss in June.</div>",
    }
    assert "soap_note_unavailable" not in details
    assert "SOAP note" in result["guidance"]


@pytest.mark.asyncio
async def test_entry_with_null_metadata_keeps_the_full_key_set(monkeypatch) -> None:
    """strip_empty_values recurses into every dict in a list, including each
    soap_entries item — an entry whose entry_name/entry_type/entry_chart_section
    came back null or "" from the EHR must not silently lose that key. The
    per-entry contract promises all five keys on every entry, regardless of
    which fields are null upstream (caught in PR review)."""
    sparse_entry = {
        "entry_id": 9,
        "entry_name": None,
        "entry_type": "",
        "entry_chart_section": "Symptoms",
        "answer": "yes",
        "is_entry_deleted": "false",
        "is_answer_deleted": "false",
    }
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"entries": [sparse_entry], "notes": {}},
    }))

    result = await _review(monkeypatch, fake)

    entry = result["encounter_details"]["soap_entries"][0]
    assert set(entry.keys()) == {
        "entry_id", "entry_name", "entry_type", "entry_chart_section", "answer",
    }
    assert entry["entry_name"] is None
    assert entry["entry_type"] == ""


@pytest.mark.asyncio
async def test_entry_id_is_passed_through_as_a_string(monkeypatch) -> None:
    """cortex cites entry_id, so an int from the API must become a string, not
    silently stay an int that a downstream citation check could mismatch."""
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"entries": [LIVE_ENTRY], "notes": {}},
    }))

    result = await _review(monkeypatch, fake)

    assert isinstance(result["encounter_details"]["soap_entries"][0]["entry_id"], str)


@pytest.mark.asyncio
async def test_deleted_entry_and_deleted_answer_are_dropped(monkeypatch) -> None:
    deleted_entry = {**LIVE_ENTRY, "entry_id": 2, "is_entry_deleted": "true"}
    deleted_answer = {**LIVE_ENTRY, "entry_id": 3, "is_answer_deleted": "true"}
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"entries": [LIVE_ENTRY, deleted_entry, deleted_answer], "notes": {}},
    }))

    result = await _review(monkeypatch, fake)

    ids = [e["entry_id"] for e in result["encounter_details"]["soap_entries"]]
    assert ids == ["100234000001234567"]


@pytest.mark.asyncio
async def test_empty_and_null_answers_are_dropped(monkeypatch) -> None:
    empty_answer = {**LIVE_ENTRY, "entry_id": 4, "answer": ""}
    null_answer = {**LIVE_ENTRY, "entry_id": 5, "answer": None}
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"entries": [LIVE_ENTRY, empty_answer, null_answer], "notes": {}},
    }))

    result = await _review(monkeypatch, fake)

    ids = [e["entry_id"] for e in result["encounter_details"]["soap_entries"]]
    assert ids == ["100234000001234567"]


@pytest.mark.asyncio
async def test_is_deleted_flags_are_not_in_the_output(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"entries": [LIVE_ENTRY], "notes": {}},
    }))

    result = await _review(monkeypatch, fake)

    entry = result["encounter_details"]["soap_entries"][0]
    assert "is_entry_deleted" not in entry
    assert "is_answer_deleted" not in entry


@pytest.mark.asyncio
async def test_null_and_empty_note_fields_are_omitted(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"entries": [], "notes": NOTES},
    }))

    result = await _review(monkeypatch, fake)

    notes = result["encounter_details"]["soap_notes"]
    assert "physical_examination" not in notes
    assert "past_medical_history" not in notes


@pytest.mark.asyncio
async def test_empty_entries_and_notes_still_present_on_success(monkeypatch) -> None:
    """Both keys must be present whenever the read succeeded, even when empty
    -- distinguishing "nothing documented" from "couldn't check". This is the
    case strip_empty_values would otherwise break for soap_notes, since it
    unconditionally drops empty dicts."""
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"entries": [], "notes": {}},
    }))

    result = await _review(monkeypatch, fake)

    details = result["encounter_details"]
    assert details["soap_entries"] == []
    assert details["soap_notes"] == {}
    assert "soap_note_unavailable" not in details


@pytest.mark.asyncio
async def test_failed_soap_read_sets_unavailable_and_omits_both_keys(monkeypatch) -> None:
    """A failed read must never look like an empty note: cortex reads "no
    note" and "unknown" differently, so the two cases cannot share a shape."""
    fake = _FakeAPIClient(get_responses=_base_responses(
        soap={"error": "HTTP 503: Service Unavailable"},
    ))

    result = await _review(monkeypatch, fake)

    details = result["encounter_details"]
    assert details["soap_note_unavailable"] is True
    assert "soap_entries" not in details
    assert "soap_notes" not in details
    assert "could not be read just now" in result["guidance"]


@pytest.mark.asyncio
async def test_soap_fetch_exception_also_sets_unavailable(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses=_base_responses(),
        errors={"/soap/encounters/e1": RuntimeError("boom")},
    )

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["soap_note_unavailable"] is True
    assert "error" not in result


# ── clinical_notes source — same invariant, same pattern, mirrored exactly
# for the GET /encounters/{id} fetch that now also supplies vitals/diagnoses/
# medications/supplements/lab_orders alongside clinical_notes.


@pytest.mark.asyncio
async def test_review_surfaces_clinical_notes(monkeypatch) -> None:
    responses = _base_responses(soap={"soap_encounter": {"entries": [], "notes": {}}})
    responses["/encounters/e1"] = {"encounter": {
        "medications": [],
        "notes": {
            "chief_complaints": "<div>Persistent worry.</div>",
            "symptoms": "<div>Restlessness.</div>",
            "history_of_present_illness": None,
            "past_medical_history": "",
        },
    }}
    fake = _FakeAPIClient(get_responses=responses)

    result = await _review(monkeypatch, fake)

    details = result["encounter_details"]
    assert details["clinical_notes"] == {
        "chief_complaints": "<div>Persistent worry.</div>",
        "symptoms": "<div>Restlessness.</div>",
    }
    assert "clinical_data_unavailable" not in details
    assert "Clinical Notes: present" in result["guidance"]


@pytest.mark.asyncio
async def test_empty_clinical_data_still_present_on_success(monkeypatch) -> None:
    """Same invariant as test_empty_entries_and_notes_still_present_on_success:
    a genuinely empty clinical_notes must survive strip_empty_values and stay
    distinguishable from clinical_data_unavailable."""
    responses = _base_responses(soap={"soap_encounter": {"entries": [], "notes": {}}})
    responses["/encounters/e1"] = {"encounter": {
        "vital_entry": {"vitals": []}, "diagnoses": [], "medications": [],
        "supplements": [], "lab_order": {"order_tests": []}, "notes": {},
    }}
    fake = _FakeAPIClient(get_responses=responses)

    result = await _review(monkeypatch, fake)

    details = result["encounter_details"]
    assert details["vitals"] == []
    assert details["clinical_notes"] == {}
    assert "clinical_data_unavailable" not in details


@pytest.mark.asyncio
async def test_failed_encounter_detail_read_sets_clinical_data_unavailable(monkeypatch) -> None:
    """A failed read must never look like nothing documented — same invariant
    as the SOAP note above, now covering this whole bundle since they share
    one fetch."""
    responses = _base_responses(soap={"soap_encounter": {"entries": [], "notes": {}}})
    responses["/encounters/e1"] = {"error": "HTTP 503: Service Unavailable"}
    fake = _FakeAPIClient(get_responses=responses)

    result = await _review(monkeypatch, fake)

    details = result["encounter_details"]
    assert details["clinical_data_unavailable"] is True
    for key in (
        "vitals", "diagnoses", "medications", "supplements", "lab_orders",
        "injections", "vaccines", "image_orders", "addendums", "handouts",
        "follow_up", "clinical_notes",
    ):
        assert key not in details
    assert "could not be read just now" in result["guidance"]


@pytest.mark.asyncio
async def test_encounter_detail_fetch_exception_also_sets_unavailable(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses=_base_responses(soap={"soap_encounter": {"entries": [], "notes": {}}}),
        errors={"/encounters/e1": RuntimeError("boom")},
    )

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["clinical_data_unavailable"] is True
    assert "error" not in result


# ── medication sourcing: client-side filtering retired, server trusted ──
#
# Superseded by the single-call rewrite: medications/diagnoses/vitals/
# supplements/lab_orders now all come from GET /encounters/{id}
# (ChartsAPIHandler.fetchChartNoteDetails) instead of /patients/{id}/medications
# filtered client-side by encounter_id. The date-matching fallback these two
# tests originally guarded against doesn't exist to regress anymore — there
# is no client-side filtering logic left at all. The CH-1352 evidence model
# (a medication must carry a real encounter_id to count as belonging to this
# encounter, never a date match) is instead enforced authoritatively
# server-side: fetchMedicationListForPatients joins on
# ConsultationMedicationMap.CONSULTATION_ID = encounterId, a real foreign-key
# relationship, not a heuristic (confirmed in ChartsAPIHandler.java). So the
# only thing left to test here is that the response's medications are passed
# through as-is, trusting that join.


@pytest.mark.asyncio
async def test_medications_come_from_the_single_encounter_fetch(monkeypatch) -> None:
    med = {"drug_name": "Sertraline", "encounter_id": "e1"}
    fake = _FakeAPIClient(get_responses=_base_responses(
        soap={"soap_encounter": {"entries": [], "notes": {}}},
        medications=[med],
    ))

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["medications"] == [med]
    assert "/patients/p1/medications" not in fake.get_calls


# ── injections/vaccines/image_orders/addendums/handouts/follow_up — the
# same single GET /encounters/{id} fetch also carries these, confirmed live
# against the real backend. Passed through as-is, same trust as medications
# above.


@pytest.mark.asyncio
async def test_review_surfaces_the_remaining_encounter_detail_categories(monkeypatch) -> None:
    injection = {"drug_name": "Vitamin B12"}
    vaccine = {"vaccine_name": "Influenza"}
    image_order = {"test_name": "Chest X-ray"}
    addendum = {"addendum_text": "Clarified dosage."}
    handout = {"handout_name": "GAD patient education"}
    follow_up_item = {"follow_up_notes": "Return in 4 weeks"}
    responses = _base_responses(soap={"soap_encounter": {"entries": [], "notes": {}}})
    responses["/encounters/e1"] = {"encounter": {
        "medications": [],
        "injections": [injection],
        "vaccines": [vaccine],
        "image_orders": [image_order],
        "addendums": [addendum],
        "handouts": [handout],
        "follow_up": [follow_up_item],
        "notes": {},
    }}
    fake = _FakeAPIClient(get_responses=responses)

    result = await _review(monkeypatch, fake)

    details = result["encounter_details"]
    assert details["injections"] == [injection]
    assert details["vaccines"] == [vaccine]
    assert details["image_orders"] == [image_order]
    assert details["addendums"] == [addendum]
    assert details["handouts"] == [handout]
    assert details["follow_up"] == [follow_up_item]
    assert "1 injection(s)" in "\n".join(result["summary"])
    assert "1 vaccine(s)" in "\n".join(result["summary"])
    assert "1 imaging order(s)" in "\n".join(result["summary"])
    assert "1 addendum(s)" in "\n".join(result["summary"])
    assert "1 handout(s) given" in "\n".join(result["summary"])
    assert "1 follow-up item(s)" in "\n".join(result["summary"])


@pytest.mark.asyncio
async def test_review_surfaces_the_expanded_clinical_note_fields(monkeypatch) -> None:
    responses = _base_responses(soap={"soap_encounter": {"entries": [], "notes": {}}})
    responses["/encounters/e1"] = {"encounter": {
        "medications": [],
        "notes": {
            "chief_complaints": "<div>Persistent worry.</div>",
            "assessment_notes": "Meets criteria for GAD.",
            "treatment_notes": "Psychoeducation provided.",
            "review_of_systems": "Negative except as noted.",
            "follow_up_appointment": "4 weeks",
            "instructions": "Continue worry-time technique.",
            "diets": "",
            "life_style": None,
            "nurse_notes": "Vitals stable.",
            "self_notes": "Private provider note.",
        },
    }}
    fake = _FakeAPIClient(get_responses=responses)

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["clinical_notes"] == {
        "chief_complaints": "<div>Persistent worry.</div>",
        "assessment_notes": "Meets criteria for GAD.",
        "treatment_notes": "Psychoeducation provided.",
        "review_of_systems": "Negative except as noted.",
        "follow_up_appointment": "4 weeks",
        "instructions": "Continue worry-time technique.",
        "nurse_notes": "Vitals stable.",
        "self_notes": "Private provider note.",
    }
