"""Regression tests for mcp-server-fix-tracker.md #6 and #9:

#6: managePatientAllergies' update branch used to do a flat required-field
check (record_id, allergen, allergy_type, severity, allergy_status,
reactions, allergy_date all mandatory) with no fetch-and-merge fallback —
unlike its sibling managePatientDrugs, which already fetches the current
record and merge-fills anything the caller omitted. Confirmed live: a card
that correctly displayed the full current allergy only sent the fields
actually changing, and the call 400'd listing the omitted ones as "missing".
Fix: fetch the current allergy row first and merge-fill allergen/type/
severity/status/reactions/date from it for anything not explicitly passed,
mirroring managePatientDrugs' established pattern (clinical_data.py update
branch for substance_type="medication").

#9: the #6 fix above mapped the list output's *key* names (patient_allergy_id
-> record_id, "type" -> allergy_type, "observed_on" -> date) but not
"status"'s *value* vocabulary — the raw list row's status is a boolean-shaped
flag ("1"/"0", "true"/"false", confirmed live), not the write side's
"Active"/"Inactive" enum word the PUT payload needs. A caller that omitted
allergy_status (the exact case #6 exists to support) got the raw flag
forwarded unmapped and a clean 400. Fix: decode the raw flag the same way
common/app_views.py's _decode_status already does for display (checking
"display_status" then "status", same precedence), mirrored rather than
imported since this is a write-side value translation, not formatting."""

from __future__ import annotations

import datetime

import pytest
from fastmcp.exceptions import ToolError

from tools import clinical_data


class _FakeAPIClient:
    def __init__(self, get_responses=None, put_responses=None):
        self._get = get_responses or {}
        self._put = put_responses or {}
        self.put_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get.get(endpoint, {})

    async def put(self, endpoint, data=None, params=None):
        self.put_calls.append((endpoint, data))
        return self._put[endpoint]


def _patch(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(clinical_data, "CharmHealthAPIClient", lambda **kwargs: fake_client)


_CURRENT_ALLERGY = {
    "patient_allergy_id": "a1",
    "allergen": "Penicillin",
    "type": "Drug",
    "severity": "Severe",
    "status": "Active",
    "reactions": ["Hives", "Swelling"],
    "observed_on": "2024-03-11",
}


@pytest.mark.asyncio
async def test_update_with_only_severity_preserves_every_other_current_field(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/allergies": {"allergies": [_CURRENT_ALLERGY]}},
        put_responses={"/patients/p1/allergies/a1": {"patient_allergy": {"id": "a1"}}},
    )
    _patch(monkeypatch, fake)

    result = await clinical_data.managePatientAllergies(
        action="update", patient_id="p1", record_id="a1", severity="Moderate",
    )

    assert "error" not in result
    _, sent_data = fake.put_calls[0]
    assert sent_data == {
        "allergen": "Penicillin",
        "type": "Drug",
        "severity": "Moderate",
        "status": "Active",
        "reactions": "Hives, Swelling",
        "date": "2024-03-11",
    }


@pytest.mark.asyncio
async def test_update_explicit_fields_override_the_fetched_current_values(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/allergies": {"allergies": [_CURRENT_ALLERGY]}},
        put_responses={"/patients/p1/allergies/a1": {"patient_allergy": {"id": "a1"}}},
    )
    _patch(monkeypatch, fake)

    await clinical_data.managePatientAllergies(
        action="update", patient_id="p1", record_id="a1",
        reactions="Rash only", allergy_date=datetime.date(2026, 1, 1),
    )

    _, sent_data = fake.put_calls[0]
    assert sent_data["reactions"] == "Rash only"
    assert sent_data["date"] == "2026-01-01"
    # untouched fields still come from the fetched record
    assert sent_data["allergen"] == "Penicillin"
    assert sent_data["severity"] == "Severe"


@pytest.mark.asyncio
async def test_update_raw_boolean_status_flag_is_decoded_to_the_write_enum(monkeypatch) -> None:
    """Live bug (CH-1954 tracker #9): the list row's "status" is a raw
    "true"/"1"-shaped flag, not "Active"/"Inactive" — omitting
    allergy_status must not forward that flag unmapped."""
    current = {**_CURRENT_ALLERGY, "status": "true"}
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/allergies": {"allergies": [current]}},
        put_responses={"/patients/p1/allergies/a1": {"patient_allergy": {"id": "a1"}}},
    )
    _patch(monkeypatch, fake)

    await clinical_data.managePatientAllergies(
        action="update", patient_id="p1", record_id="a1", severity="Moderate",
    )

    _, sent_data = fake.put_calls[0]
    assert sent_data["status"] == "Active"


@pytest.mark.asyncio
async def test_update_raw_boolean_status_flag_false_decodes_to_inactive(monkeypatch) -> None:
    current = {**_CURRENT_ALLERGY, "status": "0"}
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/allergies": {"allergies": [current]}},
        put_responses={"/patients/p1/allergies/a1": {"patient_allergy": {"id": "a1"}}},
    )
    _patch(monkeypatch, fake)

    await clinical_data.managePatientAllergies(
        action="update", patient_id="p1", record_id="a1", severity="Moderate",
    )

    _, sent_data = fake.put_calls[0]
    assert sent_data["status"] == "Inactive"


@pytest.mark.asyncio
async def test_update_display_status_key_takes_precedence_over_raw_status(monkeypatch) -> None:
    """Matches app_views.py's allergy_list_view precedence: "display_status"
    checked before "status" when both are present on the row."""
    current = {**_CURRENT_ALLERGY, "status": "0", "display_status": "true"}
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/allergies": {"allergies": [current]}},
        put_responses={"/patients/p1/allergies/a1": {"patient_allergy": {"id": "a1"}}},
    )
    _patch(monkeypatch, fake)

    await clinical_data.managePatientAllergies(
        action="update", patient_id="p1", record_id="a1", severity="Moderate",
    )

    _, sent_data = fake.put_calls[0]
    assert sent_data["status"] == "Active"


@pytest.mark.asyncio
async def test_update_explicit_allergy_status_still_overrides_the_fetched_flag(monkeypatch) -> None:
    current = {**_CURRENT_ALLERGY, "status": "true"}
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/allergies": {"allergies": [current]}},
        put_responses={"/patients/p1/allergies/a1": {"patient_allergy": {"id": "a1"}}},
    )
    _patch(monkeypatch, fake)

    await clinical_data.managePatientAllergies(
        action="update", patient_id="p1", record_id="a1", allergy_status="Inactive",
    )

    _, sent_data = fake.put_calls[0]
    assert sent_data["status"] == "Inactive"


@pytest.mark.asyncio
async def test_update_unknown_record_id_returns_not_found_without_calling_put(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={"/patients/p1/allergies": {"allergies": [_CURRENT_ALLERGY]}})
    _patch(monkeypatch, fake)

    with pytest.raises(ToolError):
        await clinical_data.managePatientAllergies(
            action="update", patient_id="p1", record_id="does-not-exist", severity="Moderate",
        )

    assert fake.put_calls == []


@pytest.mark.asyncio
async def test_update_missing_record_id_still_errors_without_fetching(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch(monkeypatch, fake)

    with pytest.raises(ToolError):
        await clinical_data.managePatientAllergies(action="update", patient_id="p1", severity="Moderate")

    assert fake.put_calls == []
