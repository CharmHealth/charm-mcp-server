"""Regression test for managePatientFiles/send_phr_invite email normalization
(mcp-server-fix-tracker.md #3's outstanding sub-item: field-format validation
applied only to managePatient, not every tool taking an email/phone field).
Mirrors the managePatient phone/email pattern in
tests/test_managePatient_field_validation.py."""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from tools import clinical_support


class _FakeAPIClient:
    def __init__(self, post_responses=None):
        self._post = post_responses or {}
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, endpoint, data=None, params=None, files=None):
        self.post_calls.append((endpoint, data))
        return self._post[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(clinical_support, "CharmHealthAPIClient", lambda **kwargs: fake_client)


@pytest.mark.asyncio
async def test_send_phr_invite_email_is_lowercased(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/invitations": {"code": "0"},
    })
    _patch_client(monkeypatch, fake)

    result = await clinical_support.managePatientFiles(
        action="send_phr_invite", patient_id="p1", email="JOHN.DOE@EXAMPLE.COM",
    )

    assert "error" not in result
    _, sent_data = fake.post_calls[0]
    assert sent_data["email"] == "john.doe@example.com"


@pytest.mark.asyncio
async def test_send_phr_invite_invalid_email_returns_field_keyed_error_without_calling_api(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientFiles(
            action="send_phr_invite", patient_id="p1", email="not-an-email",
        )

    assert "email" in json.loads(str(exc_info.value))["field_errors"]
    assert fake.post_calls == []
