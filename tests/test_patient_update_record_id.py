"""CH-1574: a partial patient update keeps the record id.

The EHR refuses any update to an existing patient whose body has no
record_id ("Patient Record Id is mandatory", PatientsBeanImpl), including one
sent with update_specific_details. Found when a confirmed email change on the
AWS-hosted EHR came back HTTP 400 with code 79; the rule dates from 2018, so
the Zoho-hosted EHR has it too.
"""

from __future__ import annotations

import pytest

from tools import patient_management

CURRENT = {"patient": {
    "patient_id": "p1", "record_id": "PAT0003", "first_name": "Cortex",
    "last_name": "Sessionforward", "gender": "unknown", "dob": "2000-01-01",
    "facilities": [{"facility_id": "73"}],
}}


class _RecordingClient:
    def __init__(self):
        self.puts: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return CURRENT

    async def put(self, endpoint, data=None, params=None):
        self.puts.append((endpoint, data))
        return {"patient": {**CURRENT["patient"], **(data or {})}}


@pytest.fixture
def client(monkeypatch):
    fake = _RecordingClient()
    monkeypatch.setattr(patient_management, "CharmHealthAPIClient", lambda **kwargs: fake)
    return fake


@pytest.mark.asyncio
async def test_a_partial_update_sends_the_current_record_id(client) -> None:
    await patient_management.managePatient(
        action="update", patient_id="p1", email="c@example.com",
        update_specific_details=True,
    )

    (endpoint, body) = client.puts[0]
    assert endpoint == "/patients/p1"
    assert body["record_id"] == "PAT0003"
    assert body["update_specific_details"] == "true"


@pytest.mark.asyncio
async def test_a_record_id_argument_still_replaces_it(client) -> None:
    await patient_management.managePatient(
        action="update", patient_id="p1", record_id="PAT9999",
        update_specific_details=True,
    )

    assert client.puts[0][1]["record_id"] == "PAT9999"


@pytest.mark.asyncio
async def test_a_full_update_still_sends_it(client) -> None:
    await patient_management.managePatient(action="update", patient_id="p1", email="c@example.com")

    assert client.puts[0][1]["record_id"] == "PAT0003"
