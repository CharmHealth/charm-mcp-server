"""Tests for manageEncounter(action="review")'s attached_templates — CH-416.

A SOAP encounter's templates reach it either from the practice's visit-type
configuration (attached by CharmHealth at creation) or from an explicit
manageEncounter(action="update", template_ids=...). A client populating
entries needs to read back what is attached either way; before this, the
only call that fetched /soap/encounters/{id} was the sign action's existence
check, which discarded the templates.

Fakes CharmHealthAPIClient — same pattern as test_procedure_codes_ch790.py.
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


def _base_responses(soap=None):
    responses = {
        "/encounters": {"encounters": [{
            "encounter_id": "e1", "date": "2026-09-21",
            "physician_name": "Dr. Jones", "facility_id": "f1",
            "visit_name": "New Patient Visit", "is_approved": "false",
        }]},
        "/patients/p1": {"patient": {"first_name": "Amy", "last_name": "Test"}},
    }
    if soap is not None:
        responses["/soap/encounters/e1"] = soap
    return responses


async def _review(monkeypatch, fake):
    _patch_client(monkeypatch, fake)
    return await encounter_management.manageEncounter.fn(
        action="review", patient_id="p1", encounter_id="e1",
    )


@pytest.mark.asyncio
async def test_review_surfaces_attached_templates(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"templates": [
            {"template_id": "t1", "template_name": "New Patient SOAP",
             "position": "1", "is_template_deleted": "false"},
        ]},
    }))

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["attached_templates"] == [
        {"template_id": "t1", "template_name": "New Patient SOAP", "position": "1"},
    ]
    assert "New Patient SOAP (template_id t1)" in result["guidance"]


@pytest.mark.asyncio
async def test_review_drops_deleted_templates(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"templates": [
            {"template_id": "t1", "template_name": "Live", "is_template_deleted": "false"},
            {"template_id": "t2", "template_name": "Removed", "is_template_deleted": "true"},
        ]},
    }))

    result = await _review(monkeypatch, fake)

    ids = [t["template_id"] for t in result["encounter_details"]["attached_templates"]]
    assert ids == ["t1"]


@pytest.mark.asyncio
async def test_soap_encounter_with_no_templates_reports_none_attached(monkeypatch) -> None:
    """Empty list is a real answer — the chart can carry templates and has none."""
    fake = _FakeAPIClient(get_responses=_base_responses(soap={
        "soap_encounter": {"templates": []},
    }))

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["attached_templates"] == []
    assert "none attached" in result["guidance"]


@pytest.mark.asyncio
async def test_non_soap_chart_omits_the_key_entirely(monkeypatch) -> None:
    """/soap/encounters/{id} only exists for SOAP charts. A Quick/Brief chart
    must not be described as having zero templates — it can't have any."""
    fake = _FakeAPIClient(
        get_responses=_base_responses(),
        errors={"/soap/encounters/e1": RuntimeError("HTTP 404: Invalid URL Passed")},
    )

    result = await _review(monkeypatch, fake)

    assert "attached_templates" not in result["encounter_details"]
    assert "SOAP Templates" not in result["guidance"]
    # The rest of the review still came back.
    assert result["encounter_details"]["encounter_info"]["encounter_id"] == "e1"


@pytest.mark.asyncio
async def test_soap_fetch_failure_does_not_break_review(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses=_base_responses(),
        errors={"/soap/encounters/e1": RuntimeError("boom")},
    )

    result = await _review(monkeypatch, fake)

    assert result["action"] == "review"
    assert "error" not in result
