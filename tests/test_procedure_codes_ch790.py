"""Tests for CH-790's procedure-coding slice: getPracticeInfo(info_type="procedure_codes")
and manageEncounterProcedures.

Fakes CharmHealthAPIClient so no real network/API access is needed — same pattern as
test_billing.py. Endpoint shapes here are confirmed against charm-charmehr's actual
routing config (webapps/ehr/WEB-INF/conf/api/rest/v1/APIRequestBy*.xml) and
InvoicesAPI.java/InvoicesAPIUtil.java, not just CH-489's ticket text — in particular,
the add/update POST body is a batch envelope ({"procedures": [...]}), not a flat
single-procedure object; a flat body would NPE server-side on
inputStream.optJSONArray("procedures").
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from tools import core_tools, billing


class _FakeAPIClient:
    """Stands in for CharmHealthAPIClient — returns canned responses keyed
    by exact endpoint string, per HTTP method."""

    def __init__(self, get_responses=None, post_responses=None, delete_responses=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self._delete = delete_responses or {}
        self.post_calls: list[tuple[str, dict]] = []
        self.delete_calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get[endpoint]

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data))
        return self._post[endpoint]

    async def delete(self, endpoint, params=None):
        self.delete_calls.append(endpoint)
        return self._delete.get(endpoint, {})


def _patch_client(monkeypatch, module, fake_client) -> None:
    monkeypatch.setattr(module, "CharmHealthAPIClient", lambda **kwargs: fake_client)


# ── getPracticeInfo(info_type="procedure_codes") ──────────────────────────


@pytest.mark.asyncio
async def test_get_practice_info_procedure_codes_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/billing/procedures": {"procedures": [
            {"code_id": "c1", "code_number": "99214", "code_name": "Office visit"},
        ]},
    })
    _patch_client(monkeypatch, core_tools, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="procedure_codes")

    assert result["procedure_code_count"] == 1
    assert result["procedure_codes"][0]["code_number"] == "99214"


@pytest.mark.asyncio
async def test_get_practice_info_procedure_codes_empty_catalog(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={"/billing/procedures": {}})
    _patch_client(monkeypatch, core_tools, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="procedure_codes")

    assert result["procedure_code_count"] == 0


@pytest.mark.asyncio
async def test_get_practice_info_procedure_codes_defaults_to_procedure_type_only(monkeypatch) -> None:
    """Unfiltered, this previously fetched the entire fee schedule including lab
    codes on every call. code_type should always be pinned to PROCEDURE_CODE so
    LAB_CODE rows aren't mixed in with nothing marking which is which (PR #22
    review)."""
    captured = {}

    class _CapturingClient(_FakeAPIClient):
        async def get(self, endpoint, params=None):
            captured["endpoint"] = endpoint
            captured["params"] = params
            return self._get[endpoint]

    fake = _CapturingClient(get_responses={"/billing/procedures": {"procedures": []}})
    _patch_client(monkeypatch, core_tools, fake)

    await core_tools.getPracticeInfo.fn(info_type="procedure_codes")

    assert captured["params"] == {"code_type": "PROCEDURE_CODE"}


@pytest.mark.asyncio
async def test_get_practice_info_procedure_codes_filters_by_code_number(monkeypatch) -> None:
    """The real endpoint documents code_id/code_name/code_number as lookup
    filters — passing one should scope the request instead of always pulling
    the whole catalog (PR #22 review)."""
    captured = {}

    class _CapturingClient(_FakeAPIClient):
        async def get(self, endpoint, params=None):
            captured["params"] = params
            return self._get[endpoint]

    fake = _CapturingClient(get_responses={
        "/billing/procedures": {"procedures": [{"code_id": "c1", "code_number": "99214"}]},
    })
    _patch_client(monkeypatch, core_tools, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="procedure_codes", code_number="99214")

    assert captured["params"] == {"code_type": "PROCEDURE_CODE", "code_number": "99214"}
    assert result["procedure_code_count"] == 1


# ── manageEncounterProcedures: list ────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_procedures_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/encounters/e1/procedures": {"procedures": [
            {"consultation_cpt_map_id": "cpt1", "code_number": "99214"},
        ]},
    })
    _patch_client(monkeypatch, billing, fake)

    result = await billing.manageEncounterProcedures.fn(action="list", patient_id="p1", encounter_id="e1")

    assert result["total_count"] == 1
    assert "1 procedure(s)" in result["guidance"]


@pytest.mark.asyncio
async def test_list_procedures_missing_ids_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, billing, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.manageEncounterProcedures.fn(action="list", patient_id="p1", encounter_id="")

    assert "encounter_id" in json.loads(str(exc_info.value))["error"]


@pytest.mark.asyncio
async def test_list_procedures_surfaces_real_api_failure_instead_of_empty_state(monkeypatch) -> None:
    """On a GET failure (bad encounter_id, expired auth, 404/500),
    CharmHealthAPIClient._make_request returns only {"error": "..."} with no
    "procedures" key. Before this fix, `response.get("procedures") or []`
    turned that into an empty list, so the caller saw total_count=0 and
    "No procedures attached to this encounter yet" instead of the real
    error — indistinguishable from an encounter that's genuinely
    uncoded (PR #22 review)."""
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/encounters/e1/procedures": {"error": "HTTP 404: Not Found"},
    })
    _patch_client(monkeypatch, billing, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.manageEncounterProcedures.fn(action="list", patient_id="p1", encounter_id="e1")

    result = json.loads(str(exc_info.value))
    assert result["error"] == "HTTP 404: Not Found"
    assert "procedures" not in result
    assert "No procedures attached" not in result.get("guidance", "")


# ── manageEncounterProcedures: add ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_procedure_sends_batch_envelope_with_defaults(monkeypatch) -> None:
    """The real API (InvoicesAPIUtil.addOrUpdateCPTsForEncounter) reads
    inputStream.optJSONArray("procedures") — a flat body would NPE server-side.
    Also confirms place_of_service defaults to "11" (Office) per CH-489's
    acceptance criteria."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/encounters/e1/procedures": {"procedures": [{"code_id": "c1"}]},
    })
    _patch_client(monkeypatch, billing, fake)

    result = await billing.manageEncounterProcedures.fn(
        action="add", patient_id="p1", encounter_id="e1", code_id="c1", item_charge=150.0,
    )

    endpoint, sent_data = fake.post_calls[0]
    assert endpoint == "/patients/p1/encounters/e1/procedures"
    assert sent_data == {"procedures": [{
        "item_quantity": 1, "place_of_service": "11", "code_id": "c1", "item_charge": 150.0,
    }]}
    assert "added to" in result["guidance"]


@pytest.mark.asyncio
async def test_add_procedure_missing_code_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, billing, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.manageEncounterProcedures.fn(
            action="add", patient_id="p1", encounter_id="e1", item_charge=150.0,
        )

    assert json.loads(str(exc_info.value))["error"] == "code_id required for add"


@pytest.mark.asyncio
async def test_add_procedure_missing_item_charge_returns_clean_error(monkeypatch) -> None:
    """item_charge is a hard requirement server-side (jObject.getDouble, not
    optDouble) — no catalog-default fallback exists, so this must fail loud
    and early rather than send a null charge."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, billing, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.manageEncounterProcedures.fn(action="add", patient_id="p1", encounter_id="e1", code_id="c1")

    assert json.loads(str(exc_info.value))["error"] == "item_charge required for add"


@pytest.mark.asyncio
async def test_add_procedure_invalid_place_of_service_rejected(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, billing, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.manageEncounterProcedures.fn(
            action="add", patient_id="p1", encounter_id="e1", code_id="c1", item_charge=150.0,
            place_of_service="63",  # not in the legal 01-62,65,71,72,81,99 set
        )

    assert "Invalid place_of_service" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_add_procedure_with_modifiers_and_diagnosis_links(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/encounters/e1/procedures": {"procedures": []},
    })
    _patch_client(monkeypatch, billing, fake)

    await billing.manageEncounterProcedures.fn(
        action="add", patient_id="p1", encounter_id="e1", code_id="c1", item_charge=150.0,
        modifier_1="25", related_diagnosis_ids="d1, d2",
    )

    _, sent_data = fake.post_calls[0]
    procedure_item = sent_data["procedures"][0]
    assert procedure_item["modifier_1"] == "25"
    assert procedure_item["related_diagnosis_ids"] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_add_procedure_accepts_native_array_for_diagnosis_links(monkeypatch) -> None:
    """A calling model that just fetched diagnosis IDs via
    manageDiagnoses(action='list') has a native list in hand, not a
    comma-separated string. related_diagnosis_ids must accept that
    directly rather than only a str (PR #22 review)."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/encounters/e1/procedures": {"procedures": []},
    })
    _patch_client(monkeypatch, billing, fake)

    await billing.manageEncounterProcedures.fn(
        action="add", patient_id="p1", encounter_id="e1", code_id="c1", item_charge=150.0,
        related_diagnosis_ids=["d1", "d2"],
    )

    _, sent_data = fake.post_calls[0]
    procedure_item = sent_data["procedures"][0]
    assert procedure_item["related_diagnosis_ids"] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_add_procedure_accepts_json_encoded_array_for_diagnosis_links(monkeypatch) -> None:
    """Some callers stringify a native array into JSON instead of sending
    it natively (same pitfall CLAUDE.md documents for create_template's
    `questions`) — tolerate that too, not just comma-separated."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/encounters/e1/procedures": {"procedures": []},
    })
    _patch_client(monkeypatch, billing, fake)

    await billing.manageEncounterProcedures.fn(
        action="add", patient_id="p1", encounter_id="e1", code_id="c1", item_charge=150.0,
        related_diagnosis_ids=json.dumps(["d1", "d2"]),
    )

    _, sent_data = fake.post_calls[0]
    procedure_item = sent_data["procedures"][0]
    assert procedure_item["related_diagnosis_ids"] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_add_procedure_invoice_already_generated_error_is_explained(monkeypatch) -> None:
    """addOrUpdateProcedure throws FinanceException.INVOICE_GENERATED when an
    invoice already exists for the encounter and skip_invoice_check wasn't set —
    the tool should surface this as an actionable guidance, not a raw error.
    The guidance must NOT coach the model to retry with skip_invoice_check=True —
    that's a billing-safety override and belongs to a human decision, not the
    agent that just got told the magic flag (PR #22 review)."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/encounters/e1/procedures": {
            "error": "Invoice already generated for the encounter specified with ID 123",
        },
    })
    _patch_client(monkeypatch, billing, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.manageEncounterProcedures.fn(
            action="add", patient_id="p1", encounter_id="e1", code_id="c1", item_charge=150.0,
        )

    guidance = json.loads(str(exc_info.value))["guidance"]
    assert "skip_invoice_check" not in guidance
    assert "surface this to the user" in guidance


# ── manageEncounterProcedures: update ──────────────────────────────────────


@pytest.mark.asyncio
async def test_update_procedure_includes_consultation_cpt_map_id_in_body(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/encounters/e1/procedures": {"procedures": [{"consultation_cpt_map_id": "cpt1"}]},
    })
    _patch_client(monkeypatch, billing, fake)

    await billing.manageEncounterProcedures.fn(
        action="update", patient_id="p1", encounter_id="e1",
        consultation_cpt_map_id="cpt1", item_charge=200.0,
    )

    _, sent_data = fake.post_calls[0]
    procedure_item = sent_data["procedures"][0]
    assert procedure_item["item_charge"] == 200.0
    assert procedure_item["consultation_cpt_map_id"] == "cpt1"


@pytest.mark.asyncio
async def test_update_procedure_does_not_overwrite_unspecified_fields(monkeypatch) -> None:
    """Before this fix, item_quantity and place_of_service were unconditionally
    sent using their parameter defaults (1 / "11"), so an update that only meant
    to change item_charge silently reset quantity and place of service on the
    real bill too — both are claim-adjudication-relevant fields (PR #22 review,
    critical finding)."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/encounters/e1/procedures": {"procedures": [{"consultation_cpt_map_id": "cpt1"}]},
    })
    _patch_client(monkeypatch, billing, fake)

    await billing.manageEncounterProcedures.fn(
        action="update", patient_id="p1", encounter_id="e1",
        consultation_cpt_map_id="cpt1", item_charge=200.0,
    )

    _, sent_data = fake.post_calls[0]
    procedure_item = sent_data["procedures"][0]
    assert "item_quantity" not in procedure_item
    assert "place_of_service" not in procedure_item


@pytest.mark.asyncio
async def test_update_procedure_applies_explicitly_supplied_fields(monkeypatch) -> None:
    """When the caller does supply item_quantity/place_of_service on an update,
    those values must still go through — the fix only skips fields the caller
    left unset, it doesn't drop them entirely."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/encounters/e1/procedures": {"procedures": [{"consultation_cpt_map_id": "cpt1"}]},
    })
    _patch_client(monkeypatch, billing, fake)

    await billing.manageEncounterProcedures.fn(
        action="update", patient_id="p1", encounter_id="e1",
        consultation_cpt_map_id="cpt1", item_quantity=3, place_of_service="02",
    )

    _, sent_data = fake.post_calls[0]
    procedure_item = sent_data["procedures"][0]
    assert procedure_item["item_quantity"] == 3
    assert procedure_item["place_of_service"] == "02"


@pytest.mark.asyncio
async def test_update_procedure_missing_map_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, billing, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.manageEncounterProcedures.fn(action="update", patient_id="p1", encounter_id="e1")

    assert json.loads(str(exc_info.value))["error"] == "consultation_cpt_map_id required for update"


# ── manageEncounterProcedures: delete ──────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_procedure_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, billing, fake)

    result = await billing.manageEncounterProcedures.fn(
        action="delete", patient_id="p1", encounter_id="e1", consultation_cpt_map_id="cpt1",
    )

    assert fake.delete_calls == ["/patients/p1/encounters/e1/procedures/cpt1"]
    assert "removed" in result["guidance"]


@pytest.mark.asyncio
async def test_delete_procedure_missing_map_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, billing, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.manageEncounterProcedures.fn(action="delete", patient_id="p1", encounter_id="e1")

    assert "consultation_cpt_map_id" in json.loads(str(exc_info.value))["error"]
    assert fake.delete_calls == []
