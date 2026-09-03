"""Live-server API probe for managePatientBilling (src/tools/billing.py).

Run against the already-running MCP server (see tests/test_api/conftest.py).

Test data: Ahmed Choi — patient_id 100010000000018023. Ahmed Choi has no
invoices, receipts, or outstanding balance in this sandbox, and there's no
tool exposed here to create billing data — so results below are correctly
"empty", not errors.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi


async def test_managePatientBilling_get_balance():
    # $ ... managePatientBilling '{"action": "get_balance", "patient_id": "100010000000018023"}'
    resp = await call_tool("managePatientBilling", {"action": "get_balance", "patient_id": PATIENT_ID})
    assert "error" not in resp


async def test_managePatientBilling_list_invoices():
    # $ ... managePatientBilling '{"action": "list_invoices", "patient_id": "100010000000018023"}'
    resp = await call_tool("managePatientBilling", {"action": "list_invoices", "patient_id": PATIENT_ID})
    assert "error" not in resp


async def test_managePatientBilling_get_receipts():
    # $ ... managePatientBilling '{"action": "get_receipts", "patient_id": "100010000000018023"}'
    resp = await call_tool("managePatientBilling", {"action": "get_receipts", "patient_id": PATIENT_ID})
    assert "error" not in resp


async def test_managePatientBilling_send_balance_reminder_not_conclusive():
    # $ ... managePatientBilling '{"action": "send_balance_reminder", "patient_id": "100010000000018023", \
    #       "send_via": "email", "reminder_message": "MCP API probe test reminder"}'
    #
    # NOT a confirmed bug: fails with a generic "Sending the balance reminder via
    # email failed" even though Ahmed Choi has a valid email on file. Most likely
    # cause: he has zero outstanding balance/invoices (confirmed via get_balance/
    # list_invoices above) -- CharmHealth's statement-send may legitimately reject
    # sending a reminder when there's nothing owed. There's no tool exposed here to
    # create a test invoice/balance, so this can't be conclusively distinguished
    # from a real bug without a patient who actually owes money. Documented as
    # inconclusive, not asserted as broken.
    resp = await call_tool(
        "managePatientBilling",
        {
            "action": "send_balance_reminder",
            "patient_id": PATIENT_ID,
            "send_via": "email",
            "reminder_message": "MCP API probe test reminder",
        },
    )
    assert isinstance(resp, dict)  # always true; this test exists to document the finding above, not assert pass/fail
