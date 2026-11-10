"""Regression tests for mcp-server-fix-tracker.md #5: each tool's own "list"
action returns rows keyed by the backing API's own id field name
(patient_diagnosis_id / patient_allergy_id / patient_medication_id /
patient_supplement_id / patient_recall_id), not "record_id" — but
"update"/"delete" only ever accepted "record_id". A model that read a row
from "list" and echoed its own id key straight back on "delete" got a
Pydantic "Unexpected keyword argument" rejection, confirmed live on
managePatientDiagnoses (session with patient John Wick, PAT0002, 2026-11-09).

Fix: each affected tool now also accepts its own list-output key name as an
alias, resolved to the same place record_id goes, before any action runs."""

from __future__ import annotations

import pytest

from tools import clinical_data, clinical_support


class _FakeAPIClient:
    def __init__(self, delete_responses=None):
        self._delete = delete_responses or {}
        self.delete_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def delete(self, endpoint, params=None):
        self.delete_calls.append(endpoint)
        return self._delete[endpoint]


def _patch(monkeypatch, module, fake_client) -> None:
    monkeypatch.setattr(module, "CharmHealthAPIClient", lambda **kwargs: fake_client)


@pytest.mark.asyncio
async def test_managePatientDiagnoses_delete_accepts_the_list_outputs_own_key(monkeypatch) -> None:
    fake = _FakeAPIClient(delete_responses={"/patients/p1/diagnoses/d1": {"code": "0"}})
    _patch(monkeypatch, clinical_data, fake)

    result = await clinical_data.managePatientDiagnoses(
        action="delete", patient_id="p1", patient_diagnosis_id="d1",
    )

    assert "error" not in result
    assert fake.delete_calls == ["/patients/p1/diagnoses/d1"]


@pytest.mark.asyncio
async def test_managePatientAllergies_delete_accepts_the_list_outputs_own_key(monkeypatch) -> None:
    fake = _FakeAPIClient(delete_responses={"/patients/p1/allergies/a1": {"code": "0"}})
    _patch(monkeypatch, clinical_data, fake)

    result = await clinical_data.managePatientAllergies(
        action="delete", patient_id="p1", patient_allergy_id="a1",
    )

    assert "error" not in result
    assert fake.delete_calls == ["/patients/p1/allergies/a1"]


@pytest.mark.asyncio
async def test_managePatientDrugs_discontinue_accepts_the_list_outputs_own_key(monkeypatch) -> None:
    fake = _FakeAPIClient()
    get_responses = {"/patients/p1/medications": {"medications": [{"patient_medication_id": "m1", "drug_name": "Lisinopril"}]}}
    async def _get(endpoint, params=None):
        return get_responses.get(endpoint, {})
    fake.get = _get
    fake.put_calls = []
    async def _put(endpoint, data=None, params=None):
        fake.put_calls.append((endpoint, data))
        return {"medications": [{"id": "m1"}]}
    fake.put = _put
    _patch(monkeypatch, clinical_data, fake)

    result = await clinical_data.managePatientDrugs(
        action="discontinue", patient_id="p1", substance_type="medication", patient_medication_id="m1",
    )

    assert "error" not in result
    assert fake.put_calls[0][0] == "/patients/p1/medications/m1"


@pytest.mark.asyncio
async def test_managePatientRecalls_delete_accepts_the_list_outputs_own_key(monkeypatch) -> None:
    fake = _FakeAPIClient(delete_responses={"/patients/p1/recalls/r1": {"code": "0"}})
    _patch(monkeypatch, clinical_support, fake)

    result = await clinical_support.managePatientRecalls(
        action="delete", patient_id="p1", patient_recall_id="r1",
    )

    assert "error" not in result
    assert fake.delete_calls == ["/patients/p1/recalls/r1"]


@pytest.mark.asyncio
async def test_record_id_still_wins_when_both_are_somehow_passed(monkeypatch) -> None:
    """record_id stays the primary field; the alias is only a fallback."""
    fake = _FakeAPIClient(delete_responses={"/patients/p1/diagnoses/explicit": {"code": "0"}})
    _patch(monkeypatch, clinical_data, fake)

    await clinical_data.managePatientDiagnoses(
        action="delete", patient_id="p1", record_id="explicit", patient_diagnosis_id="aliased",
    )

    assert fake.delete_calls == ["/patients/p1/diagnoses/explicit"]
