"""Tests for managePatientLabs' order action.

Fakes CharmHealthAPIClient so no real network/API access is needed — same
pattern as test_referrals.py.

order's order_tests items each need lab_id/lab_name/medical_record_id/
lab_record_id — validated client-side before ever calling the API, since the
real backend NPEs on a missing order_tests array entirely rather than
returning a clean 400. There is no lookup action in this tool to discover
those catalog values (search_labs/search_tests were removed — the real
GET /labs/list and GET /lab/{id}/tests/search endpoints require an OAuth
scope this app's credentials don't carry, confirmed via live testing against
sandbox, not fixable from this tool). Callers must supply real catalog
values from elsewhere.
"""

from __future__ import annotations

import datetime
import json

import pytest
from fastmcp.exceptions import ToolError

from tools import clinical_support


class _FakeAPIClient:
    """Stands in for CharmHealthAPIClient — returns canned responses keyed
    by exact endpoint string, per HTTP method."""

    def __init__(self, get_responses=None, post_responses=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self.get_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        self.get_calls.append((endpoint, params or {}))
        return self._get[endpoint]

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data or {}))
        return self._post[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(clinical_support, "CharmHealthAPIClient", lambda **kwargs: fake_client)


# ── order ────────────────────────────────────────────────────────────────


_VALID_TEST = {"lab_id": "1", "lab_name": "LabCorp", "medical_record_id": "500", "lab_record_id": "600"}


@pytest.mark.asyncio
async def test_order_missing_patient_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs.fn(action="order", encounter_id="e1", order_tests=[_VALID_TEST])

    assert json.loads(str(exc_info.value))["error"] == "patient_id required for order"
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_order_requires_encounter_or_member_and_facility(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs.fn(
            action="order", patient_id="p1", order_tests=[_VALID_TEST],
        )

    assert "encounter_id" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_order_requires_non_empty_order_tests(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs.fn(
            action="order", patient_id="p1", encounter_id="e1",
        )

    assert "order_tests" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_order_rejects_test_missing_required_fields(monkeypatch) -> None:
    """The real backend NPEs on a malformed order_tests item rather than
    400ing cleanly — catch this client-side instead."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs.fn(
            action="order", patient_id="p1", encounter_id="e1",
            order_tests=[{"lab_id": "1", "lab_name": "LabCorp"}],  # missing medical_record_id/lab_record_id
        )

    error = json.loads(str(exc_info.value))["error"]
    assert "order_tests[0]" in error
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_order_happy_path_with_encounter_id(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/labs/order": {"lab_orders_list": ["9001", "9002"]},
    })
    _patch_client(monkeypatch, fake)

    result = await clinical_support.managePatientLabs.fn(
        action="order", patient_id="p1", encounter_id="e1", order_tests=[_VALID_TEST],
    )

    endpoint, sent_body = fake.post_calls[0]
    assert endpoint == "/patients/p1/labs/order"
    assert sent_body == {"encounter_id": "e1", "order_tests": [_VALID_TEST]}
    assert result["lab_order_ids"] == ["9001", "9002"]
    assert result["guidance"] == "Lab order placed."


@pytest.mark.asyncio
async def test_order_happy_path_with_member_and_facility(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/patients/p1/labs/order": ["9001"],
    })
    _patch_client(monkeypatch, fake)

    result = await clinical_support.managePatientLabs.fn(
        action="order", patient_id="p1", member_id="m1", facility_id="f1",
        ordered_date=datetime.date(2026, 8, 7), order_tests=[_VALID_TEST],
    )

    _, sent_body = fake.post_calls[0]
    assert sent_body["member_id"] == "m1"
    assert sent_body["facility_id"] == "f1"
    assert sent_body["ordered_date"] == "2026-08-07"
    # Bare-array response (not wrapped) must also parse correctly.
    assert result["lab_order_ids"] == ["9001"]


@pytest.mark.asyncio
async def test_order_accepts_stringified_order_tests(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={"/patients/p1/labs/order": {"lab_orders_list": ["9001"]}})
    _patch_client(monkeypatch, fake)

    await clinical_support.managePatientLabs.fn(
        action="order", patient_id="p1", encounter_id="e1",
        order_tests=json.dumps([_VALID_TEST]),
    )

    _, sent_body = fake.post_calls[0]
    assert sent_body["order_tests"] == [_VALID_TEST]


@pytest.mark.asyncio
async def test_order_rejects_malformed_order_tests_json_string(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs.fn(
            action="order", patient_id="p1", encounter_id="e1",
            order_tests="not valid json{",
        )

    assert "order_tests" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []
