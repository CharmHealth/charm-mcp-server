"""Tests for canonical <entity>_name fields (J13/CH-695, task 5 prep).

Additive only: each tool already returns some raw field with the display
name (full_name, supplement_name, or a nested owner object) — these tests
confirm the new canonical field is added alongside it, with the same
value, without disturbing the original field. Fakes CharmHealthAPIClient
so no real network/API access is needed.
"""

from __future__ import annotations

import pytest

from tools import core_tools, patient_management, clinical_data, task_management, encounter_management, scheduling_tools


class _FakeAPIClient:
    """Stands in for CharmHealthAPIClient — returns canned responses keyed
    by exact endpoint string, per HTTP method."""

    def __init__(self, get_responses=None, post_responses=None, put_responses=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self._put = put_responses or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get[endpoint]

    async def post(self, endpoint, data=None, params=None):
        return self._post[endpoint]

    async def put(self, endpoint, data=None, params=None):
        return self._put[endpoint]


def _patch_client(monkeypatch, module, fake_client) -> None:
    monkeypatch.setattr(module, "CharmHealthAPIClient", lambda **kwargs: fake_client)


@pytest.mark.asyncio
async def test_find_patients_adds_patient_name(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients": {"patients": [
            {"id": "p1", "first_name": "Jane", "last_name": "Smith", "full_name": "Jane Smith"},
        ]},
    })
    _patch_client(monkeypatch, core_tools, fake)

    result = await core_tools.findPatients.fn(query="Jane")

    patient = result["patients"][0]
    assert patient["full_name"] == "Jane Smith"
    assert patient["patient_name"] == "Jane Smith"


@pytest.mark.asyncio
async def test_get_practice_info_providers_adds_provider_name(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/members": {"members": [
            {"member_id": "m1", "first_name": "Alex", "last_name": "Doe", "full_name": "Alex Doe"},
        ]},
    })
    _patch_client(monkeypatch, core_tools, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="providers")

    provider = result["providers"][0]
    assert provider["full_name"] == "Alex Doe"
    assert provider["provider_name"] == "Alex Doe"


@pytest.mark.asyncio
async def test_manage_patient_create_adds_patient_name(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients": {"patient": {
            "patient_id": "p1", "first_name": "Jane", "last_name": "Smith", "full_name": "Jane Smith",
        }},
    })
    _patch_client(monkeypatch, patient_management, fake)

    result = await patient_management.managePatient.fn(
        action="create", first_name="Jane", last_name="Smith",
        gender="female", facility_ids="1", age="30",
    )

    assert result["patient"]["patient_name"] == "Jane Smith"
    assert result["patient"]["full_name"] == "Jane Smith"


@pytest.mark.asyncio
async def test_manage_patient_update_adds_patient_name(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={
            "/patients/p1": {"patient": {
                "patient_id": "p1", "first_name": "Jane", "last_name": "Smith",
                "gender": "female", "dob": "1990-01-01", "facilities": [],
            }},
        },
        put_responses={
            "/patients/p1": {"patient": {
                "patient_id": "p1", "first_name": "Jane", "last_name": "Smith", "full_name": "Jane Smith",
            }},
        },
    )
    _patch_client(monkeypatch, patient_management, fake)

    result = await patient_management.managePatient.fn(action="update", patient_id="p1")

    assert result["patient"]["patient_name"] == "Jane Smith"


@pytest.mark.asyncio
async def test_manage_patient_drugs_list_supplements_adds_drug_name(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/supplements": {"supplements": [
            {"supplement_id": "s1", "supplement_name": "Vitamin D3", "status": "Active"},
        ]},
    })
    _patch_client(monkeypatch, clinical_data, fake)

    result = await clinical_data.managePatientDrugs.fn(
        action="list", patient_id="p1", substance_type="supplement",
    )

    supplement = result["supplements"][0]
    assert supplement["supplement_name"] == "Vitamin D3"
    assert supplement["drug_name"] == "Vitamin D3"


@pytest.mark.asyncio
async def test_manage_tasks_list_flattens_owner_id_and_name(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/tasks": {"tasks": [
            {
                "task_id": "t1", "task": "Follow up",
                "owner": {"member_id": "m1", "full_name": "Alex Doe", "prefix": "Dr."},
            },
        ]},
    })
    _patch_client(monkeypatch, task_management, fake)

    result = await task_management.manageTasks.fn(action="list")

    task = result["tasks"][0]
    assert task["owner"] == {"member_id": "m1", "full_name": "Alex Doe", "prefix": "Dr."}
    assert task["owner_id"] == "m1"
    assert task["owner_name"] == "Alex Doe"


@pytest.mark.asyncio
async def test_manage_encounter_review_adds_provider_name(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/encounters": {"encounters": [
            {"encounter_id": "e1", "physician_name": "Dr. Alex Doe", "date": "2026-07-01",
             "facility_id": "f1", "appointment_mode": "In Person", "visit_name": "Follow-up",
             "is_approved": "true"},
        ]},
        "/patients/p1": {"patient": {"patient_id": "p1"}},
        "/patients/p1/vitals": {"vital_entries": []},
        "/patients/p1/diagnoses": {"diagnoses": []},
        "/patients/p1/medications": {"medications": []},
        "/patients/p1/supplements": {"supplements": []},
        "/patients/p1/lab-orders": {"lab_orders": []},
    })
    _patch_client(monkeypatch, encounter_management, fake)

    result = await encounter_management.manageEncounter.fn(
        patient_id="p1", action="review", encounter_id="e1",
    )

    info = result["encounter_details"]["encounter_info"]
    assert info["provider"] == "Dr. Alex Doe"
    assert info["provider_name"] == "Dr. Alex Doe"


@pytest.mark.asyncio
async def test_manage_appointments_list_adds_provider_name(monkeypatch) -> None:
    import datetime

    fake = _FakeAPIClient(get_responses={
        "/appointments": {"appointments": [
            {"appointment_id": "a1", "member_id": "m1", "physician_name": "Dr. Alex Doe",
             "appointment_status": "Confirmed"},
        ]},
    })
    _patch_client(monkeypatch, scheduling_tools, fake)

    result = await scheduling_tools.manageAppointments.fn(
        action="list",
        start_date=datetime.date(2026, 7, 1),
        end_date_range=datetime.date(2026, 7, 31),
        facility_ids="1",
    )

    appt = result["appointments"][0]
    assert appt["provider_name"] == "Dr. Alex Doe"
