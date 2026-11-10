"""Regression tests for mcp-server-fix-tracker.md #7: manageAppointments'
reschedule branch did a single `all()` over six required fields and, on
failure, returned a generic error listing every possible required field
regardless of which one(s) were actually missing. Confirmed live: two
consecutive reschedule attempts failed with the identical message, giving
neither the model nor a human any way to tell which field was the problem
— the model's retry added irrelevant fields because it had nothing to go
on.

Fix: compute and report only the fields actually missing, mirroring the
fix already applied to managePatientAllergies' equivalent check (#6). Also
surface the auto-fill GET's own failure in guidance, when present, instead
of only logging it — a second observation from the same entry."""

from __future__ import annotations

import datetime

import pytest
from fastmcp.exceptions import ToolError

from tools import scheduling_tools


class _FakeAPIClient:
    def __init__(self, get_responses=None, post_responses=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get.get(endpoint, {})

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data))
        return self._post[endpoint]


class _RaisingGetClient(_FakeAPIClient):
    async def get(self, endpoint, params=None):
        raise RuntimeError("connection reset")


def _patch(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(scheduling_tools, "CharmHealthAPIClient", lambda **kwargs: fake_client)


@pytest.mark.asyncio
async def test_reschedule_missing_appointment_id_names_only_that_field(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await scheduling_tools.manageAppointments(
            action="reschedule", patient_id="p1", provider_id="pr1", facility_id="f1",
            appointment_date=datetime.date(2026, 11, 10), appointment_time="10:00 AM",
        )

    message = str(exc_info.value)
    assert "appointment_id" in message
    assert "facility_id" not in message.split('"error"')[1].split('"guidance"')[0]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_reschedule_missing_date_and_time_names_only_those_fields(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await scheduling_tools.manageAppointments(
            action="reschedule", appointment_id="a1", patient_id="p1",
            provider_id="pr1", facility_id="f1",
        )

    message = str(exc_info.value)
    assert "appointment_date" in message
    assert "appointment_time" in message
    assert "appointment_id" not in message.split('"error"')[1].split('"guidance"')[0]


@pytest.mark.asyncio
async def test_reschedule_autofill_failure_is_surfaced_in_guidance_not_only_logged(monkeypatch) -> None:
    fake = _RaisingGetClient()
    _patch(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await scheduling_tools.manageAppointments(
            action="reschedule", appointment_id="a1",
            appointment_date=datetime.date(2026, 11, 10), appointment_time="10:00 AM",
        )

    message = str(exc_info.value)
    assert "connection reset" in message
    assert "patient_id" in message


@pytest.mark.asyncio
async def test_reschedule_autofill_backfills_patient_id_from_appointment(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={
            "/appointment/a1": {"appointment": {
                "practice_patient_id": "1", "facility_id": "3", "member_id": "2",
            }},
        },
        post_responses={
            "/appointment/a1/reschedule": {"output_string": "ok"},
        },
    )
    _patch(monkeypatch, fake)

    result = await scheduling_tools.manageAppointments(
        action="reschedule", appointment_id="a1",
        appointment_date=datetime.date(2026, 11, 10), appointment_time="10:00 AM",
    )

    assert "error" not in result
    assert fake.post_calls[0][1]["patient_id"] == 1


@pytest.mark.asyncio
async def test_reschedule_with_all_fields_present_succeeds(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/appointment/a1/reschedule": {"output_string": "ok"},
    })
    _patch(monkeypatch, fake)

    result = await scheduling_tools.manageAppointments(
        action="reschedule", appointment_id="a1", patient_id="1", provider_id="2", facility_id="3",
        appointment_date=datetime.date(2026, 11, 10), appointment_time="10:00 AM",
    )

    assert "error" not in result
    assert fake.post_calls[0][0] == "/appointment/a1/reschedule"
