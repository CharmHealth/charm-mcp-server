"""Integration tests for managePatient's phone/email/zip normalization and
format validation (mutation-forms field-format validation fix) — the
triggering bug was a patient create with phone "(555) 014-7823" (parens +
hyphen, exactly how a user would say it) reaching the backing REST API
unnormalized and failing its `[0-9\\+-]*` regex."""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from tools import patient_management


class _FakeAPIClient:
    def __init__(self, post_responses=None):
        self._post = post_responses or {}
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data))
        return self._post[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(patient_management, "CharmHealthAPIClient", lambda **kwargs: fake_client)


@pytest.mark.asyncio
async def test_create_patient_phone_with_parens_is_normalized_before_the_rest_call(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients": {"patient": {"patient_id": "p1", "full_name": "Jane Doe"}},
    })
    _patch_client(monkeypatch, fake)

    result = await patient_management.managePatient(
        action="create", first_name="Jane", last_name="Doe", gender="female",
        age="30", facility_ids="123", phone="(555) 014-7823",
    )

    assert "error" not in result
    _, sent_data = fake.post_calls[0]
    assert sent_data["mobile"] == "555014-7823"


@pytest.mark.asyncio
async def test_create_patient_email_is_lowercased(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients": {"patient": {"patient_id": "p1", "full_name": "Jane Doe"}},
    })
    _patch_client(monkeypatch, fake)

    await patient_management.managePatient(
        action="create", first_name="Jane", last_name="Doe", gender="female",
        age="30", facility_ids="123", email="JOHN.DOE@EXAMPLE.COM",
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data["email"] == "john.doe@example.com"


@pytest.mark.asyncio
async def test_create_patient_invalid_phone_raises_field_keyed_tool_error_without_calling_api(monkeypatch) -> None:
    """`@with_tool_metrics()` promotes any `{"error": ...}` return to a raised
    ToolError — this is the established convention for every other
    validation failure in this tool (missing required fields, etc.), so a
    format-validation failure follows it too."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await patient_management.managePatient(
            action="create", first_name="Jane", last_name="Doe", gender="female",
            age="30", facility_ids="123", phone="555-CALL-NOW",
        )

    assert "phone" in json.loads(str(exc_info.value))["field_errors"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_patient_invalid_zip_raises_field_keyed_tool_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await patient_management.managePatient(
            action="create", first_name="Jane", last_name="Doe", gender="female",
            age="30", facility_ids="123", zip_code="9021",
        )

    assert "zip_code" in json.loads(str(exc_info.value))["field_errors"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_patient_non_us_zip_code_is_not_format_checked(monkeypatch) -> None:
    """The US ZIP/ZIP+4 regex must not reject a legitimate non-US postal
    code when `country` says the address isn't American."""
    fake = _FakeAPIClient(post_responses={
        "/patients": {"patient": {"patient_id": "p1", "full_name": "Jane Doe"}},
    })
    _patch_client(monkeypatch, fake)

    result = await patient_management.managePatient(
        action="create", first_name="Jane", last_name="Doe", gender="female",
        age="30", facility_ids="123", zip_code="K1A 0B1", country="CA",
    )

    assert "error" not in result
