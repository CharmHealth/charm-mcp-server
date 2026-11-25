"""CH-2081: a failed lookup GET in managePatientDrugs update/discontinue was being
misreported as "record not found" -- api_client.py's _make_request() never raises
on a failed GET, it returns {"error": "..."} as the response body, same shape as a
success. current_resp.get("<resource>", []) couldn't tell that apart from a
genuinely empty/non-matching list; both collapsed to [].

Fixed by common/utils.py's get_error_response(), called right after each GET and
before the list lookup. Three cases per call site, per the ticket's Test Cases
field: GET fails, GET succeeds but record genuinely absent, happy path.
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from tools import clinical_data
from tests.test_clinical_data import _FakeAPIClient, _patch_client


MEDICATION_RECORD = {
    "patient_medication_id": "m1",
    "directions": "Take 1 tablet daily",
    "dispense": "30",
    "refills": "0",
    "is_active": True,
    "substitute_generic": False,
    "manufacturing_type": "Manufactured",
}

SUPPLEMENT_RECORD = {
    "patient_supplement_id": "s1",
    "supplement_name": "Vitamin D",
}


@pytest.mark.asyncio
async def test_update_medication_surfaces_real_error_when_get_fails(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/medications": {"error": "HTTP 500: Internal Server Error"},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs(
            action="update", patient_id="p1", substance_type="medication",
            record_id="m1", directions="Take 2 tablets daily",
        )

    message = str(exc_info.value)
    assert "Could not verify medication m1" in message
    assert "HTTP 500" in message
    assert "not found" not in message


@pytest.mark.asyncio
async def test_update_medication_still_reports_not_found_when_get_succeeds_but_record_absent(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/medications": {"medications": [MEDICATION_RECORD]},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs(
            action="update", patient_id="p1", substance_type="medication",
            record_id="does-not-exist", directions="Take 2 tablets daily",
        )

    message = str(exc_info.value)
    assert "Medication record does-not-exist not found" in message
    assert "list" in message


@pytest.mark.asyncio
async def test_update_medication_happy_path_still_works(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/medications": {"medications": [MEDICATION_RECORD]}},
        put_responses={"/patients/p1/medications/m1": {"medications": [MEDICATION_RECORD]}},
    )
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs(
        action="update", patient_id="p1", substance_type="medication",
        record_id="m1", directions="Take 2 tablets daily",
    )

    assert len(fake.put_calls) == 1
    endpoint, sent_data = fake.put_calls[0]
    assert endpoint == "/patients/p1/medications/m1"
    assert sent_data["directions"] == "Take 2 tablets daily"


@pytest.mark.asyncio
async def test_update_supplement_surfaces_real_error_when_get_fails(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/supplements": {"error": "HTTP 503: Service Unavailable"},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs(
            action="update", patient_id="p1", substance_type="supplement",
            record_id="s1", dosage="2",
        )

    message = str(exc_info.value)
    assert "Could not verify supplement s1" in message
    assert "HTTP 503" in message
    assert "not found" not in message


@pytest.mark.asyncio
async def test_update_supplement_still_reports_not_found_when_get_succeeds_but_record_absent(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/supplements": {"supplements": [SUPPLEMENT_RECORD]},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs(
            action="update", patient_id="p1", substance_type="supplement",
            record_id="does-not-exist", dosage="2",
        )

    message = str(exc_info.value)
    assert "Supplement record does-not-exist not found" in message


@pytest.mark.asyncio
async def test_update_supplement_happy_path_still_works(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/supplements": {"supplements": [SUPPLEMENT_RECORD]}},
        put_responses={"/patients/p1/supplements/s1": {"supplements": [SUPPLEMENT_RECORD]}},
    )
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs(
        action="update", patient_id="p1", substance_type="supplement",
        record_id="s1", dosage="2",
    )

    assert len(fake.put_calls) == 1
    endpoint, _ = fake.put_calls[0]
    assert endpoint == "/patients/p1/supplements/s1"


@pytest.mark.asyncio
async def test_discontinue_medication_surfaces_real_error_when_get_fails(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/medications": {"error": "HTTP 500: Internal Server Error"},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs(
            action="discontinue", patient_id="p1", substance_type="medication",
            record_id="m1",
        )

    message = str(exc_info.value)
    assert "Could not verify medication m1" in message
    assert "HTTP 500" in message
    assert "not found" not in message


@pytest.mark.asyncio
async def test_discontinue_medication_still_reports_not_found_when_get_succeeds_but_record_absent(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/medications": {"medications": [MEDICATION_RECORD]},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs(
            action="discontinue", patient_id="p1", substance_type="medication",
            record_id="does-not-exist",
        )

    message = str(exc_info.value)
    assert "Medication record does-not-exist not found" in message


@pytest.mark.asyncio
async def test_discontinue_medication_happy_path_still_works(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/medications": {"medications": [MEDICATION_RECORD]}},
        put_responses={"/patients/p1/medications/m1": {"medications": [MEDICATION_RECORD]}},
    )
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs(
        action="discontinue", patient_id="p1", substance_type="medication",
        record_id="m1",
    )

    assert len(fake.put_calls) == 1
    endpoint, sent_data = fake.put_calls[0]
    assert endpoint == "/patients/p1/medications/m1"
    assert sent_data["is_active"] is False


@pytest.mark.asyncio
async def test_discontinue_supplement_surfaces_real_error_when_get_fails(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/supplements": {"error": "HTTP 503: Service Unavailable"},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs(
            action="discontinue", patient_id="p1", substance_type="supplement",
            record_id="s1",
        )

    message = str(exc_info.value)
    assert "Could not verify supplement s1" in message
    assert "HTTP 503" in message
    assert "not found" not in message


@pytest.mark.asyncio
async def test_discontinue_supplement_still_reports_not_found_when_get_succeeds_but_record_absent(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/supplements": {"supplements": [SUPPLEMENT_RECORD]},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs(
            action="discontinue", patient_id="p1", substance_type="supplement",
            record_id="does-not-exist",
        )

    message = str(exc_info.value)
    assert "Supplement record does-not-exist not found" in message


@pytest.mark.asyncio
async def test_discontinue_supplement_happy_path_still_works(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/supplements": {"supplements": [SUPPLEMENT_RECORD]}},
        put_responses={"/patients/p1/supplements/s1": {"supplements": [SUPPLEMENT_RECORD]}},
    )
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs(
        action="discontinue", patient_id="p1", substance_type="supplement",
        record_id="s1",
    )

    assert len(fake.put_calls) == 1
    endpoint, _ = fake.put_calls[0]
    assert endpoint == "/patients/p1/supplements/s1"
