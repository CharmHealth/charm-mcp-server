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

import json

import pytest
from fastmcp.exceptions import ToolError

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


def _base_responses(soap=None, chart_type="SOAP"):
    responses = {
        "/encounters": {"encounters": [{
            "encounter_id": "e1", "date": "2026-09-21",
            "physician_name": "Dr. Jones", "facility_id": "f1",
            "visit_name": "New Patient Visit", "is_approved": "false",
            "chart_type": chart_type,
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
async def test_non_soap_chart_reports_none_without_suggesting_a_soap_template(monkeypatch) -> None:
    """CharmHealth answers the SOAP read for every chart type — a Brief or
    Comprehensive chart gets success with an empty list (checked live
    2026-09-23). So "none attached" is true, but offering to attach a SOAP
    template to a non-SOAP chart would not be."""
    fake = _FakeAPIClient(get_responses=_base_responses(
        soap={"soap_encounter": {"templates": []}}, chart_type="Brief",
    ))

    result = await _review(monkeypatch, fake)

    assert result["encounter_details"]["attached_templates"] == []
    assert "none attached (Brief chart)" in result["guidance"]
    assert "Attach one with" not in result["guidance"]


@pytest.mark.asyncio
async def test_failed_template_read_is_flagged_not_silent(monkeypatch) -> None:
    """The client returns {"error": ...} rather than raising, so a transient
    failure used to look like "no templates" to whoever reviews before
    signing. It must be distinguishable."""
    fake = _FakeAPIClient(get_responses=_base_responses(
        soap={"error": "HTTP 503: Service Unavailable"},
    ))

    result = await _review(monkeypatch, fake)

    details = result["encounter_details"]
    assert "attached_templates" not in details
    assert details["attached_templates_unavailable"] is True
    assert "could not be read just now" in result["guidance"]
    # The rest of the review still came back.
    assert details["encounter_info"]["encounter_id"] == "e1"


@pytest.mark.asyncio
async def test_soap_fetch_failure_does_not_break_review(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses=_base_responses(),
        errors={"/soap/encounters/e1": RuntimeError("boom")},
    )

    result = await _review(monkeypatch, fake)

    assert result["action"] == "review"
    assert "error" not in result


# ── manageEncounter(action="update") template attach ───────────────────
#
# CharmHealth attaches a visit type's configured templates itself when an
# encounter is created with a visit type (confirmed 2026-09-23 on both
# create paths). So update now often runs against an encounter that already
# has templates. Three things it used to get wrong:
#   - numbered each call's templates from 0, colliding with the
#     auto-attached template at position 0
#   - reported a template as attached without checking the response;
#     client.post returns {"error": ...} rather than raising
#   - re-sent templates already there; CharmHealth dedupes silently but
#     answers "added successfully", which was passed on as fact
# And a template-only call POSTed an empty body to save "entries", whose
# failure reported the whole call as failed.


class _UpdateFakeClient:
    def __init__(self, templates=None, soap_error=None, attach_responses=None,
                 save_response=None):
        self._templates = templates
        self._soap_error = soap_error
        self._attach = attach_responses or {}
        self._save = save_response if save_response is not None else {"code": "0"}
        self.posts: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        if endpoint == "/soap/encounters/e1":
            if self._soap_error:
                raise self._soap_error
            if self._templates is None:
                return {"error": "HTTP 503: Service Unavailable"}
            return {"soap_encounter": {"templates": self._templates}}
        return {}

    async def post(self, endpoint, data=None, params=None):
        self.posts.append((endpoint, data))
        if endpoint == "/soap/encounters/e1/template":
            return self._attach.get(data["template_id"], {"code": "0", "message": "Soap template added successfully."})
        return self._save

    def attach_calls(self):
        return [d for e, d in self.posts if e.endswith("/template")]

    def save_calls(self):
        return [d for e, d in self.posts if e == "/soap/encounters/e1"]


AUTO = {"template_id": "tA", "template_name": "Visit type SOAP", "position": "0", "is_template_deleted": "false"}


async def _update(monkeypatch, fake, **kwargs):
    monkeypatch.setattr(encounter_management, "CharmHealthAPIClient", lambda **kw: fake)
    return await encounter_management.manageEncounter.fn(
        action="update", patient_id="p1", encounter_id="e1", **kwargs,
    )


@pytest.mark.asyncio
async def test_new_template_goes_after_the_auto_attached_one(monkeypatch) -> None:
    fake = _UpdateFakeClient(templates=[AUTO])

    result = await _update(monkeypatch, fake, template_ids="tB")

    assert fake.attach_calls() == [{"template_id": "tB", "position": "1"}]
    assert result["templates_attached"] == ["tB"]


@pytest.mark.asyncio
async def test_already_attached_template_is_skipped_and_reported(monkeypatch) -> None:
    """CharmHealth would answer "added successfully" to the repeat — the
    tool must not pass that on as a fresh attach."""
    fake = _UpdateFakeClient(templates=[AUTO])

    result = await _update(monkeypatch, fake, template_ids="tA")

    assert fake.attach_calls() == []
    assert result["already_attached"] == ["tA"]
    assert "templates_attached" not in result


@pytest.mark.asyncio
async def test_mixed_call_skips_the_existing_and_numbers_the_new(monkeypatch) -> None:
    fake = _UpdateFakeClient(templates=[AUTO])

    result = await _update(monkeypatch, fake, template_ids="tA,tB,tC")

    assert fake.attach_calls() == [
        {"template_id": "tB", "position": "1"},
        {"template_id": "tC", "position": "2"},
    ]
    assert result["already_attached"] == ["tA"]
    assert result["templates_attached"] == ["tB", "tC"]


@pytest.mark.asyncio
async def test_a_repeat_within_one_call_is_sent_once(monkeypatch) -> None:
    fake = _UpdateFakeClient(templates=[])

    result = await _update(monkeypatch, fake, template_ids="tB,tB")

    assert fake.attach_calls() == [{"template_id": "tB", "position": "0"}]
    assert result["templates_attached"] == ["tB"]
    assert result["already_attached"] == ["tB"]


@pytest.mark.asyncio
async def test_deleted_templates_keep_their_slot(monkeypatch) -> None:
    """A soft-deleted template doesn't count as attached, but its position
    isn't reused either."""
    deleted = {"template_id": "tX", "position": "2", "is_template_deleted": "true"}
    fake = _UpdateFakeClient(templates=[AUTO, deleted])

    result = await _update(monkeypatch, fake, template_ids="tX")

    assert fake.attach_calls() == [{"template_id": "tX", "position": "3"}]
    assert result["templates_attached"] == ["tX"]


@pytest.mark.asyncio
async def test_rejected_attach_is_reported_as_failed(monkeypatch) -> None:
    """The old loop appended every id, because client.post returns an error
    dict instead of raising."""
    fake = _UpdateFakeClient(
        templates=[AUTO],
        attach_responses={"tB": {"error": "HTTP 400: Invalid template_id"}},
    )

    result = await _update(monkeypatch, fake, template_ids="tB,tC")

    assert result["templates_attached"] == ["tC"]
    assert result["templates_failed"] == [
        {"template_id": "tB", "reason": "HTTP 400: Invalid template_id"},
    ]
    assert "could not be attached" in result["guidance"]
    # The failed one didn't take a slot: tC gets the position tB would have.
    assert fake.attach_calls()[1] == {"template_id": "tC", "position": "1"}


@pytest.mark.asyncio
async def test_partial_attach_is_not_a_protocol_error(monkeypatch) -> None:
    """A nested failure reason must not trip the metrics decorator, which
    raises ToolError on a top-level "error" key."""
    fake = _UpdateFakeClient(
        templates=[AUTO],
        attach_responses={"tB": {"error": "HTTP 400: nope"}},
    )

    result = await _update(monkeypatch, fake, template_ids="tB")

    assert "error" not in result
    assert result["templates_failed"][0]["template_id"] == "tB"


@pytest.mark.asyncio
async def test_template_only_update_sends_no_empty_save(monkeypatch) -> None:
    fake = _UpdateFakeClient(templates=[AUTO], save_response={"code": "1", "message": "empty body"})

    result = await _update(monkeypatch, fake, template_ids="tB")

    assert fake.save_calls() == []
    assert result["templates_attached"] == ["tB"]


@pytest.mark.asyncio
async def test_failed_save_keeps_the_attach_results(monkeypatch) -> None:
    fake = _UpdateFakeClient(templates=[AUTO], save_response={"code": "1"})

    with pytest.raises(ToolError) as exc_info:
        await _update(monkeypatch, fake, template_ids="tB", chief_complaint="cough")

    body = json.loads(str(exc_info.value))
    assert body["error"] == "Failed to update encounter"
    assert body["templates_attached"] == ["tB"]
    assert "don't re-attach" in body["guidance"]


@pytest.mark.asyncio
async def test_unreadable_encounter_attaches_nothing(monkeypatch) -> None:
    """If the read of what's attached fails, any position picked could collide
    with the auto-attached template — so nothing is attached, and every
    requested template is reported as failed for the caller to retry."""
    fake = _UpdateFakeClient(templates=None)

    result = await _update(monkeypatch, fake, template_ids="tA,tB,tA")

    assert fake.attach_calls() == []
    assert [f["template_id"] for f in result["templates_failed"]] == ["tA", "tB"]
    assert "retry" in result["templates_failed"][0]["reason"]
    assert "templates_attached" not in result


@pytest.mark.asyncio
async def test_notes_only_update_still_saves(monkeypatch) -> None:
    fake = _UpdateFakeClient(templates=[AUTO])

    result = await _update(monkeypatch, fake, chief_complaint="cough")

    assert fake.attach_calls() == []
    assert fake.save_calls() == [{"chief_complaints": "cough"}]
    assert result["updated"] is True


@pytest.mark.asyncio
async def test_a_no_op_update_says_so_without_reading_as_failure(monkeypatch) -> None:
    """Nothing changed, so don't claim an update — but keep "success" in the
    message, which CharmAnywhere's current decoder reads to decide success."""
    fake = _UpdateFakeClient(templates=[AUTO])

    result = await _update(monkeypatch, fake, template_ids="tA")

    assert result["updated"] is False
    assert "no changes were needed" in result["message"]
    assert "success" in result["message"]
