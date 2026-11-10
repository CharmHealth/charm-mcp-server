"""Regression test for the managePatient/update record_id bug
(mcp-server-fix-tracker.md #1): with update_specific_details=True (the
default), the backing REST API returns HTTP 400 "Patient Record Id is
mandatory" unless record_id is sent — and the tool already fetches the
current patient record (which carries record_id) but never fell back to it,
only to the caller-supplied argument. Confirmed live: two otherwise-identical
update calls, one with record_id passed explicitly and one without, differed
only in that field and only the one with it succeeded."""

from __future__ import annotations

import pytest

from tools import patient_management


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


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(patient_management, "CharmHealthAPIClient", lambda **kwargs: fake_client)


@pytest.mark.asyncio
async def test_update_without_record_id_falls_back_to_the_fetched_patients_record_id(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={
            "/patients/p1": {"patient": {
                "first_name": "Jane", "last_name": "Doe", "gender": "female",
                "dob": "1990-01-01", "record_id": "PAT0001",
            }},
        },
        put_responses={"/patients/p1": {"patient": {"patient_id": "p1", "full_name": "Jane Doe"}}},
    )
    _patch_client(monkeypatch, fake)

    result = await patient_management.managePatient(action="update", patient_id="p1", city="Springfield")

    assert "error" not in result
    _, sent_data = fake.put_calls[0]
    assert sent_data["record_id"] == "PAT0001"


@pytest.mark.asyncio
async def test_update_with_explicit_record_id_overrides_the_fetched_one(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={
            "/patients/p1": {"patient": {
                "first_name": "Jane", "last_name": "Doe", "gender": "female",
                "dob": "1990-01-01", "record_id": "PAT0001",
            }},
        },
        put_responses={"/patients/p1": {"patient": {"patient_id": "p1", "full_name": "Jane Doe"}}},
    )
    _patch_client(monkeypatch, fake)

    await patient_management.managePatient(action="update", patient_id="p1", record_id="PAT9999", city="Springfield")

    _, sent_data = fake.put_calls[0]
    assert sent_data["record_id"] == "PAT9999"
