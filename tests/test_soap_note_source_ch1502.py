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
        "/patients/p1/medications": {"medications": medications or []},
    }
    if soap is not None:
        responses["/soap/encounters/e1"] = soap
    return responses


async def _review(monkeypatch, fake):
    _patch_client(monkeypatch, fake)
    return await encounter_management.manageEncounter.fn(
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


# ── medication date-fallback removal ────────────────────────────────────


@pytest.mark.asyncio
async def test_medications_no_longer_fall_back_to_date_matching(monkeypatch) -> None:
    """A medication without this encounter's encounter_id used to be pulled
    in anyway if its date_of_entry/start_date matched the encounter's date.
    Per the CH-1352 evidence model, a date match isn't a real encounter_id
    and must not be reported as belonging to this encounter."""
    same_day_but_different_encounter = {
        "drug_name": "Sertraline", "encounter_id": "other-encounter",
        "date_of_entry": "2026-09-21", "start_date": "2026-09-21",
    }
    fake = _FakeAPIClient(get_responses=_base_responses(
        soap={"soap_encounter": {"entries": [], "notes": {}}},
        encounter_date="2026-09-21",
        medications=[same_day_but_different_encounter],
    ))

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["medications"] == []


@pytest.mark.asyncio
async def test_medications_still_match_by_real_encounter_id(monkeypatch) -> None:
    this_encounter_med = {"drug_name": "Sertraline", "encounter_id": "e1"}
    other_encounter_med = {"drug_name": "Ibuprofen", "encounter_id": "e2"}
    fake = _FakeAPIClient(get_responses=_base_responses(
        soap={"soap_encounter": {"entries": [], "notes": {}}},
        medications=[this_encounter_med, other_encounter_med],
    ))

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["medications"] == [this_encounter_med]
