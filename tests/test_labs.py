"""Tests for managePatientLabs' order action.

Fakes CharmHealthAPIClient so no real network/API access is needed — same
pattern as test_referrals.py.

order's order_tests items each need lab_id/lab_name/medical_record_id/
lab_record_id — validated client-side before ever calling the API, since the
real backend NPEs on a missing order_tests array entirely rather than
returning a clean 400.

Those values come from the catalog actions (list_labs, search_tests,
test_questions). An earlier version removed lookup actions because
GET /lab/{id}/tests/search failed on sandbox. That path is wrong — it 404s —
and the one CharmAnywhere uses, GET /labs/tests/search, answers with a token
carrying charmhealth.defaults.READ (checked against the demo practice,
2026-10-07).
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
        await clinical_support.managePatientLabs(action="order", encounter_id="e1", order_tests=[_VALID_TEST])

    assert json.loads(str(exc_info.value))["error"] == "patient_id required for order"
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_order_requires_encounter_or_member_and_facility(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs(
            action="order", patient_id="p1", order_tests=[_VALID_TEST],
        )

    assert "encounter_id" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_order_requires_non_empty_order_tests(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs(
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
        await clinical_support.managePatientLabs(
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

    result = await clinical_support.managePatientLabs(
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

    result = await clinical_support.managePatientLabs(
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

    await clinical_support.managePatientLabs(
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
        await clinical_support.managePatientLabs(
            action="order", patient_id="p1", encounter_id="e1",
            order_tests="not valid json{",
        )

    assert "order_tests" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_order_rejects_order_tests_with_non_dict_elements(monkeypatch) -> None:
    """`'["12345"]'` parses as valid JSON and IS a list, so the earlier
    list-only check passed it through — then `t.get(k)` on a bare string
    element raised AttributeError, surfacing as an opaque
    "'str' object has no attribute 'get'" instead of the guidance written
    for a malformed order_tests item."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs(
            action="order", patient_id="p1", encounter_id="e1",
            order_tests='["12345"]',
        )

    assert "order_tests" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


# ── catalog lookup ───────────────────────────────────────────────────────


def _tsh(record_id, test_id, code=""):
    return {"lab_name": "General", "lab_id": "L1", "test_name": "TSH", "test_code": code,
            "lab_record_id": record_id, "test_id": test_id}


def _params(record_id, lo, hi, loinc="11580-8"):
    return {"lab_test_params": [{"param_name": "TSH", "lab_rec_id": record_id, "loinc_code": loinc,
                                 "rec_unit": "uIU/mL", "ref_min": lo, "ref_max": hi}]}


@pytest.fixture(autouse=True)
def _clear_params_cache():
    clinical_support._test_params_cache.clear()
    yield
    clinical_support._test_params_cache.clear()


@pytest.mark.asyncio
async def test_search_tests_returns_orderable_options_with_what_tells_them_apart(monkeypatch) -> None:
    """Four entries named TSH in one lab is the demo practice's real catalog.
    By name they are identical; by reference range two of them are not."""
    fake = _FakeAPIClient(get_responses={
        "/labs/tests/search": {"lab_tests": [_tsh("R1", "T1"), _tsh("R2", "T2"), _tsh("R4", "T4", "004259")]},
        "/labs/test/R1/parameters": _params("R1", "0.33", "5.33"),
        "/labs/test/R2/parameters": _params("R2", "0.358", "3.74"),
        "/labs/test/R4/parameters": _params("R4", "0.45", "4.5"),
    })
    _patch_client(monkeypatch, fake)

    r = await clinical_support.managePatientLabs(action="search_tests", test_name="TSH")

    first = r["lab_tests"][0]
    assert first["lab_record_id"] == "R1" and first["medical_record_id"] == "T1"
    assert first["measures"][0] == {"name": "TSH", "loinc_code": "11580-8", "unit": "uIU/mL",
                                    "reference_range": "0.33-5.33"}
    assert r["lab_tests"][2]["test_code"] == "004259"
    assert "do not pick by name" in r["guidance"]
    # Same lab, same LOINC, three different ranges: one duplicate group.
    dup = r["catalog_duplicates"][0]
    assert dup["loinc_codes"] == ["11580-8"] and sorted(dup["lab_record_ids"]) == ["R1", "R2", "R4"]


@pytest.mark.asyncio
async def test_search_tests_caches_parameters_between_searches(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/labs/tests/search": {"lab_tests": [_tsh("R1", "T1")]},
        "/labs/test/R1/parameters": _params("R1", "0.33", "5.33"),
    })
    _patch_client(monkeypatch, fake)

    await clinical_support.managePatientLabs(action="search_tests", test_name="TSH")
    await clinical_support.managePatientLabs(action="search_tests", test_name="TSH")

    assert [c[0] for c in fake.get_calls].count("/labs/test/R1/parameters") == 1


@pytest.mark.asyncio
async def test_search_tests_says_when_it_stopped_looking_up_details(monkeypatch) -> None:
    many = [_tsh(f"R{i}", f"T{i}") for i in range(11)]
    responses = {"/labs/tests/search": {"lab_tests": many}}
    responses.update({f"/labs/test/R{i}/parameters": _params(f"R{i}", "0.3", "5") for i in range(11)})
    fake = _FakeAPIClient(get_responses=responses)
    _patch_client(monkeypatch, fake)

    r = await clinical_support.managePatientLabs(action="search_tests", test_name="TSH")

    assert r["details_omitted"] == 3
    assert "measures" not in r["lab_tests"][10]
    assert "narrow with lab_name" in r["guidance"]


@pytest.mark.asyncio
async def test_search_tests_requires_test_name(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs(action="search_tests")

    assert json.loads(str(exc_info.value))["error"] == "test_name required for search_tests"
    assert fake.get_calls == []


@pytest.mark.asyncio
async def test_test_questions_returns_ask_at_order_entry(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/labs/tests/R1/ask_at_order_entry": {"ask_at_order_entry": [{"code": "FAST", "description": "Fasting?"}]},
    })
    _patch_client(monkeypatch, fake)

    r = await clinical_support.managePatientLabs(action="test_questions", lab_record_id="R1")

    assert r["questions"][0]["code"] == "FAST"


@pytest.mark.asyncio
async def test_catalog_scope_failure_says_which_scope(monkeypatch) -> None:
    class _Denied(_FakeAPIClient):
        async def get(self, endpoint, params=None):
            raise RuntimeError("401 Unauthorized: invalid oauth scope")
    _patch_client(monkeypatch, _Denied())

    with pytest.raises(ToolError) as exc_info:
        await clinical_support.managePatientLabs(action="list_labs")

    assert "charmhealth.defaults.READ" in json.loads(str(exc_info.value))["guidance"]


@pytest.mark.asyncio
async def test_search_tests_flags_a_range_stored_backwards(monkeypatch) -> None:
    """Real demo data: a TSH stored as 5.5-0.35. No value is inside it."""
    fake = _FakeAPIClient(get_responses={
        "/labs/tests/search": {"lab_tests": [_tsh("R3", "T3")]},
        "/labs/test/R3/parameters": _params("R3", "5.5", "0.35", loinc=""),
    })
    _patch_client(monkeypatch, fake)

    r = await clinical_support.managePatientLabs(action="search_tests", test_name="TSH")

    assert r["inverted_ranges"] == [{"lab_name": "General", "test_name": "TSH", "lab_record_id": "R3",
                                     "measure": "TSH", "reference_range": "5.5-0.35"}]
    assert "see inverted_ranges" in r["guidance"]
