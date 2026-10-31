"""manageEncounter: the review names the encounter's facility, and unlock
reaches the EHR — CH-1901.

cortex's sign card shows the encounter as the clinician signs it, and a
facility id is not something a clinician recognizes. The list endpoint the
review reads gives the id only, so the name comes from /facilities.

Unlock posted to "/api/ehr/v1/encounters/{id}/unlock". The client's base URL
already ends in /api/ehr/v1, so the request went to the prefix twice and the
EHR answered 404 (found in the CH-1901 live run against ehr2).

Fakes CharmHealthAPIClient — same pattern as test_soap_note_source_ch1502.py.
"""

from __future__ import annotations

import pytest

from tools import encounter_management


class _FakeAPIClient:
    def __init__(self, get_responses=None, post_responses=None, errors=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self._errors = errors or {}
        self.post_calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        if endpoint in self._errors:
            raise self._errors[endpoint]
        return self._get.get(endpoint, {})

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data))
        return self._post.get(endpoint, {"code": "404", "message": "Not found"})


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(
        encounter_management, "CharmHealthAPIClient", lambda **kwargs: fake_client
    )


def _review_responses(facilities=None):
    responses = {
        "/encounters": {"encounters": [{
            "encounter_id": "e1", "date": "2026-10-30",
            "physician_name": "Dr. Jones", "facility_id": "f1",
            "is_approved": "false", "chart_type": "SOAP",
        }]},
        "/patients/p1": {"patient": {"first_name": "Amy", "last_name": "Test"}},
        "/soap/encounters/e1": {"soap_encounter": {"templates": [], "entries": [], "notes": {}}},
    }
    if facilities is not None:
        responses["/facilities"] = {"facilities": facilities}
    return responses


async def _review(monkeypatch, fake):
    _patch_client(monkeypatch, fake)
    return await encounter_management.manageEncounter(
        action="review", patient_id="p1", encounter_id="e1",
    )


@pytest.mark.asyncio
async def test_review_names_the_facility_and_keeps_its_id(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_review_responses(facilities=[
        {"facility_id": "f0", "facility_name": "Elsewhere"},
        {"facility_id": "f1", "facility_name": "Ink Inc."},
    ]))

    info = (await _review(monkeypatch, fake))["encounter_details"]["encounter_info"]

    assert info["facility_name"] == "Ink Inc."
    assert info["facility"] == "f1"


@pytest.mark.asyncio
async def test_a_failed_facilities_read_leaves_the_name_out(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses=_review_responses(),
        errors={"/facilities": RuntimeError("facilities down")},
    )

    result = await _review(monkeypatch, fake)

    info = result["encounter_details"]["encounter_info"]
    assert "facility_name" not in info
    assert info["facility"] == "f1"


@pytest.mark.asyncio
async def test_unlock_posts_under_the_client_base_url(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/encounters/e1/unlock": {"code": "0", "message": "Chart note unlocked successfully"},
    })
    _patch_client(monkeypatch, fake)

    result = await encounter_management.manageEncounter(
        action="unlock", patient_id="p1", encounter_id="e1", reason="correct a typo",
    )

    assert result["unlocked"] is True
    assert fake.post_calls == [("/encounters/e1/unlock", {"reason": "correct a typo"})]
