"""Tests for managePatientBilling (get_balance, list_invoices, get_receipts,
send_balance_reminder).

Fakes CharmHealthAPIClient so no real network/API access is needed — same
pattern as test_entity_name_fields.py. Particular focus on send_balance_reminder,
whose success-detection logic was rewritten after review found it checked a
response["code"] field the real API never returns (see billing.py comments
and the real BillingSendStatementManager.sendPatientStatement Java source).
"""

from __future__ import annotations

import datetime
import json

import pytest
from fastmcp.exceptions import ToolError

from tools import billing


class _FakeAPIClient:
    """Stands in for CharmHealthAPIClient — returns canned responses keyed
    by exact endpoint string, per HTTP method."""

    def __init__(self, get_responses=None, post_responses=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self.post_calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get[endpoint]

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data))
        return self._post[endpoint]

    async def post_form(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data))
        return self._post[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(billing, "CharmHealthAPIClient", lambda **kwargs: fake_client)


# ── get_balance ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_balance_happy_path(monkeypatch) -> None:
    # /patients/{id}/billing/balances (the detail variant) 404s against the
    # real sandbox — confirmed live, with and without facility_id. Switched
    # to /patients/{id}/balance (BillingReportsAPI.fetchPatientBalance,
    # confirmed live), whose real field is "total_balance_due".
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/balance": {"total_balance_due": 150.0, "insurance_balance_due": 0},
    })
    _patch_client(monkeypatch, fake)

    result = await billing.managePatientBilling.fn(action="get_balance", patient_id="p1")

    assert result["total_balance_due"] == 150.0
    assert "150.0" in result["guidance"]


@pytest.mark.asyncio
async def test_get_balance_zero_balance_is_not_treated_as_missing(monkeypatch) -> None:
    """A genuine $0 balance must still report correctly, not fall through
    to the 'no outstanding balance' branch as if the field were absent —
    0 is not None."""
    fake = _FakeAPIClient(get_responses={
        "/patients/p1/balance": {"total_balance_due": 0, "insurance_balance_due": 0},
    })
    _patch_client(monkeypatch, fake)

    result = await billing.managePatientBilling.fn(action="get_balance", patient_id="p1")

    assert "Patient balance retrieved" in result["guidance"]
    assert "No outstanding balance" not in result["guidance"]


@pytest.mark.asyncio
async def test_get_balance_missing_patient_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    # with_tool_metrics() raises ToolError for any {"error": ...} return —
    # the error/guidance content survives verbatim as the exception message.
    with pytest.raises(ToolError) as exc_info:
        await billing.managePatientBilling.fn(action="get_balance", patient_id="")

    body = json.loads(str(exc_info.value))
    assert body["error"] == "patient_id required for get_balance"
    assert fake.post_calls == []


# ── list_invoices / get_receipts ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_invoices_passes_filters_through(monkeypatch) -> None:
    # InvoicesAPI.fetchInvoices returns a bare JSON array — not {"invoices": [...]}.
    fake = _FakeAPIClient(get_responses={
        "/invoices": [{"invoice_id": "i1"}],
    })
    _patch_client(monkeypatch, fake)

    result = await billing.managePatientBilling.fn(
        action="list_invoices", patient_id="p1",
        start_date=datetime.date(2026, 1, 1), end_date=datetime.date(2026, 7, 1),
        per_page=10, page=2,
    )

    assert result["total_count"] == 1
    assert "1 invoice(s)" in result["guidance"]


@pytest.mark.asyncio
async def test_list_invoices_missing_patient_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.managePatientBilling.fn(action="list_invoices", patient_id="")

    assert json.loads(str(exc_info.value))["error"] == "patient_id required for list_invoices"


@pytest.mark.asyncio
async def test_get_receipts_happy_path(monkeypatch) -> None:
    # ReceiptsAPI.fetchReceipts also returns a bare JSON array.
    fake = _FakeAPIClient(get_responses={
        "/receipts": [{"receipt_id": "r1"}, {"receipt_id": "r2"}],
    })
    _patch_client(monkeypatch, fake)

    result = await billing.managePatientBilling.fn(action="get_receipts", patient_id="p1")

    assert result["total_count"] == 2
    assert "2 receipt(s)" in result["guidance"]


@pytest.mark.asyncio
async def test_get_receipts_missing_patient_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.managePatientBilling.fn(action="get_receipts", patient_id="")

    assert json.loads(str(exc_info.value))["error"] == "patient_id required for get_receipts"


# ── send_balance_reminder ─────────────────────────────────────────────
# Rewritten after review found the success check compared response["code"]
# to "0" — a field the real sendPatientStatement response never has. Real
# shape: {"successful_delivery_modes": [...], "failed_delivery_modes": [...]}.


@pytest.mark.asyncio
async def test_send_balance_reminder_defaults_to_email_channel(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/billing/statements/p1/send": {
            "successful_delivery_modes": ["EMAIL"], "failed_delivery_modes": [],
        },
    })
    _patch_client(monkeypatch, fake)

    result = await billing.managePatientBilling.fn(
        action="send_balance_reminder", patient_id="p1", reminder_message="You owe $50.",
    )

    endpoint, sent_data = fake.post_calls[0]
    assert endpoint == "/billing/statements/p1/send"
    assert sent_data == {"send_configuration": json.dumps({"email_configuration": {"content": "You owe $50."}})}
    assert "sent to the patient via email" in result["guidance"]


@pytest.mark.asyncio
async def test_send_balance_reminder_phr_channel_builds_correct_body(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/billing/statements/p1/send": {
            "successful_delivery_modes": ["PHR"], "failed_delivery_modes": [],
        },
    })
    _patch_client(monkeypatch, fake)

    result = await billing.managePatientBilling.fn(
        action="send_balance_reminder", patient_id="p1", send_via="phr",
    )

    endpoint, sent_data = fake.post_calls[0]
    assert sent_data == {"send_configuration": json.dumps({"phr_configuration": {}})}
    assert "sent to the patient via phr" in result["guidance"]


@pytest.mark.asyncio
async def test_send_balance_reminder_sms_channel_builds_correct_body(monkeypatch) -> None:
    fake = _FakeAPIClient(post_responses={
        "/billing/statements/p1/send": {
            "successful_delivery_modes": [], "failed_delivery_modes": ["TEXT_MESSAGE"],
        },
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.managePatientBilling.fn(
            action="send_balance_reminder", patient_id="p1", send_via="sms",
        )

    endpoint, sent_data = fake.post_calls[0]
    assert sent_data == {"send_configuration": json.dumps({"text_message_configuration": {}})}
    error_payload = json.loads(str(exc_info.value))
    assert "failed" in error_payload["error"]
    assert "sms" in error_payload["guidance"]


@pytest.mark.asyncio
async def test_send_balance_reminder_partial_success_reports_correctly(monkeypatch) -> None:
    """A real send can partially succeed across channels (e.g. email sent,
    a different channel failed) — success/failure here must be judged only
    against the one channel actually requested, not the response as a whole."""
    fake = _FakeAPIClient(post_responses={
        "/billing/statements/p1/send": {
            "successful_delivery_modes": ["PHR"], "failed_delivery_modes": ["EMAIL"],
        },
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.managePatientBilling.fn(
            action="send_balance_reminder", patient_id="p1", send_via="email",
        )

    assert "failed" in json.loads(str(exc_info.value))["guidance"]


@pytest.mark.asyncio
async def test_send_balance_reminder_missing_patient_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await billing.managePatientBilling.fn(action="send_balance_reminder", patient_id="")

    assert json.loads(str(exc_info.value))["error"] == "patient_id required for send_balance_reminder"
    assert fake.post_calls == []
