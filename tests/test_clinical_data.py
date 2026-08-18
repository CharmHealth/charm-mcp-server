"""Tests for managePatientDrugs' medication dispense-quantity handling and
route/dose_form/dosage_unit validation.

Covers two fixes:
1. `quantity=0` being treated as "omitted" and silently defaulted to a
   30-day supply, because the original code used a truthiness check
   (`if quantity else 30.0`) rather than an explicit `is not None` check.
2. route/dose_form/dosage_unit were briefly typed `Literal[DRUG_ROUTES]`
   etc. — FastMCP validates the protocol-level schema before the function
   body runs, so a caller sending title-case (e.g. route="Oral", which
   models naturally emit) got a bare schema rejection and never saw this
   tool's own {"error": ..., "guidance": ...} convention. Reverted to
   Optional[str] with case-insensitive validation/normalization done in
   the body instead, for substance_type="medication" only — the
   supplement/vitamin path accepted any string before and still does.
"""

from __future__ import annotations

import logging

import pytest
from fastmcp.exceptions import ToolError

from tools import clinical_data


class _FakeAPIClient:
    """Stands in for CharmHealthAPIClient — returns canned responses keyed
    by exact endpoint string, per HTTP method, and records what was sent."""

    def __init__(self, get_responses=None, post_responses=None, put_responses=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self._put = put_responses or {}
        self.post_calls = []
        self.put_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get.get(endpoint, {})

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data))
        return self._post[endpoint]

    async def put(self, endpoint, data=None, params=None):
        self.put_calls.append((endpoint, data))
        return self._put[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(clinical_data, "CharmHealthAPIClient", lambda **kwargs: fake_client)


@pytest.mark.asyncio
async def test_add_medication_explicit_quantity_zero_is_sent_not_defaulted(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/medications": {"medications": [{"id": "m1"}]},
    })
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs.fn(
        action="add", patient_id="p1", substance_type="medication",
        drug_name="Lisinopril 10mg", directions="Take 1 tablet by mouth once daily",
        quantity=0,
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data[0]["dispense"] == 0.0


@pytest.mark.asyncio
async def test_add_medication_omitted_quantity_defaults_to_30(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/medications": {"medications": [{"id": "m1"}]},
    })
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs.fn(
        action="add", patient_id="p1", substance_type="medication",
        drug_name="Lisinopril 10mg", directions="Take 1 tablet by mouth once daily",
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data[0]["dispense"] == 30.0


@pytest.mark.asyncio
async def test_add_medication_title_case_route_is_normalized_not_rejected(monkeypatch) -> None:
    """A calling model naturally emits title case (route="Oral"); the real
    catalog value is lowercase ("oral"). Must be accepted and normalized to
    the canonical casing before being sent, not rejected."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/medications": {"medications": [{"id": "m1"}]},
    })
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs.fn(
        action="add", patient_id="p1", substance_type="medication",
        drug_name="Lisinopril 10mg", directions="Take 1 tablet by mouth once daily",
        route="Oral", dose_form="Tablet", dosage_unit="MG",
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data[0]["route"] == "oral"
    assert sent_data[0]["dose_form"] == "tablet"
    assert sent_data[0]["dosage_unit"] == "mg"


@pytest.mark.asyncio
async def test_add_medication_invalid_route_returns_clean_error(monkeypatch) -> None:
    """A genuinely invalid value (not just a casing mismatch) must still be
    caught client-side with this tool's error/guidance convention, not sent
    through to the real API."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/medications": {"medications": [{"id": "m1"}]},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_data.managePatientDrugs.fn(
            action="add", patient_id="p1", substance_type="medication",
            drug_name="Lisinopril 10mg", directions="Take 1 tablet by mouth once daily",
            route="not-a-real-route",
        )

    assert "route" in str(exc_info.value)
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_add_supplement_route_accepts_any_string_unvalidated(monkeypatch) -> None:
    """The supplement/vitamin path fed by these same three params accepted
    any string before the Literal narrowing existed — that behavior must be
    preserved, not retroactively validated against the drug catalog."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/supplements": {"supplements": [{"id": "s1"}]},
    })
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs.fn(
        action="add", patient_id="p1", substance_type="supplement",
        drug_name="Vitamin D3", dosage=5,
        route="whatever the caller wants",
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data[0]["route"] == "whatever the caller wants"


@pytest.mark.asyncio
async def test_add_supplement_explicit_quantity_zero_is_sent_not_dropped(monkeypatch) -> None:
    """Same truthiness bug as the medication `dispense` fix, pre-existing on the
    supplement path's `quantity` field (`if quantity:` treated an explicit 0 as
    unset and silently dropped it from the request entirely — unlike
    medication's `dispense`, there's no default to fall back to here, so the
    field just vanished)."""
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/supplements": {"supplements": [{"id": "s1"}]},
    })
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs.fn(
        action="add", patient_id="p1", substance_type="supplement",
        drug_name="Vitamin D3", dosage=5, quantity=0,
    )

    _, sent_data = fake.post_calls[0]
    assert sent_data[0]["quantity"] == 0


@pytest.mark.asyncio
async def test_add_supplement_omitted_quantity_is_not_sent(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/supplements": {"supplements": [{"id": "s1"}]},
    })
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs.fn(
        action="add", patient_id="p1", substance_type="supplement",
        drug_name="Vitamin D3", dosage=5,
    )

    _, sent_data = fake.post_calls[0]
    assert "quantity" not in sent_data[0]


@pytest.mark.asyncio
async def test_prescribe_surfaces_allergy_warning_without_logging_allergen_names(monkeypatch, caplog) -> None:
    """The allergy safety check must reach the caller in the response guidance
    — previously it was only logger.warning()'d and never attached to the
    response, so the calling clinician/agent never actually saw which
    allergies were found despite the tool's docstring claiming an automatic
    check. Allergen names are PHI and must not appear in the application log
    either — previously logged verbatim."""
    fake = _FakeAPIClient(
        get_responses={
            "/patients/p1/allergies": {"allergies": [{"allergen": "Penicillin"}, {"allergen": "Peanuts"}]},
        },
        post_responses={"/patients/p1/medications": {"medications": [{"id": "m1"}]}},
    )
    _patch_client(monkeypatch, fake)

    with caplog.at_level(logging.WARNING):
        result = await clinical_data.managePatientDrugs.fn(
            action="prescribe", patient_id="p1", encounter_id="100010000000128111",
            drug_name="Amoxicillin 500mg", directions="Take 1 capsule twice daily",
        )

    assert "Penicillin" in result["guidance"]
    assert "Peanuts" in result["guidance"]
    assert "Penicillin" not in caplog.text
    assert "Peanuts" not in caplog.text


@pytest.mark.asyncio
async def test_add_medication_without_allergies_has_no_warning(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={"/patients/p1/allergies": {"allergies": []}},
        post_responses={"/patients/p1/medications": {"medications": [{"id": "m1"}]}},
    )
    _patch_client(monkeypatch, fake)

    result = await clinical_data.managePatientDrugs.fn(
        action="add", patient_id="p1",
        drug_name="Lisinopril 10mg", directions="Take 1 tablet daily",
    )

    assert "WARNING" not in result["guidance"]


@pytest.mark.asyncio
async def test_update_medication_preserves_explicit_dispense_zero(monkeypatch) -> None:
    """Same truthiness bug as the `add`/`prescribe` quantity=0 fix, on the
    read side: `update` fetches the current record to preserve fields the API
    requires on every PUT, and `current_med.get("dispense") or 30` treated a
    stored 0 (now a legitimately reachable value) as unset, silently
    resetting it back to a 30-day supply on any unrelated update."""
    fake = _FakeAPIClient(
        get_responses={
            "/patients/p1/medications": {"medications": [{
                "patient_medication_id": "m1", "dispense": 0, "directions": "old directions",
            }]},
        },
        put_responses={"/patients/p1/medications/m1": {"medications": [{"id": "m1"}]}},
    )
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs.fn(
        action="update", patient_id="p1", record_id="m1",
        directions="new directions",
    )

    _, sent_data = fake.put_calls[0]
    assert sent_data["dispense"] == 0.0


@pytest.mark.asyncio
async def test_discontinue_medication_preserves_explicit_dispense_zero(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={
            "/patients/p1/medications": {"medications": [{
                "patient_medication_id": "m1", "dispense": 0, "directions": "old directions",
            }]},
        },
        put_responses={"/patients/p1/medications/m1": {"medications": [{"id": "m1"}]}},
    )
    _patch_client(monkeypatch, fake)

    await clinical_data.managePatientDrugs.fn(
        action="discontinue", patient_id="p1", record_id="m1",
    )

    _, sent_data = fake.put_calls[0]
    assert sent_data["dispense"] == 0.0
