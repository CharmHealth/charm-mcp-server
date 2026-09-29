"""Live-server API probe for manageAppointments (src/tools/scheduling_tools.py).

Run against the already-running MCP server (see tests/test_api/conftest.py). Each
test is self-contained (creates its own fresh appointment) so it can be run alone
via your IDE's per-test run button.

Test data: Ahmed Choi — patient_id 100010000000018023; Peter Parker —
provider_id 100010000000000117; Charm Clinic — facility_id 100010000000008157.
"""
import random
from datetime import date, timedelta

from conftest import call_tool, TEST_DATA

PATIENT_ID = TEST_DATA["patient_id"]
PROVIDER_ID = TEST_DATA["provider_id"]
FACILITY_ID = TEST_DATA["facility_id"]


def _random_date() -> str:
    """A randomized date well spread out from this session's heavily-reused
    2026-09-20/21 test dates, so repeated runs don't collide with leftover
    (un-cancelled) appointments from earlier runs."""
    return (date(2026, 10, 1) + timedelta(days=random.randint(0, 300))).isoformat()


def _random_slot() -> str:
    """A randomized business-hours time slot — same collision-avoidance
    reasoning as _random_date."""
    hour = random.randint(9, 16)
    minute = random.choice(["00", "15", "30", "45"])
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour if hour <= 12 else hour - 12
    return f"{display_hour:02d}:{minute} {suffix}"


async def _schedule_appointment() -> str:
    resp = await call_tool(
        "manageAppointments",
        {
            "action": "schedule",
            "patient_id": PATIENT_ID,
            "provider_id": PROVIDER_ID,
            "facility_id": FACILITY_ID,
            "appointment_date": _random_date(),
            "appointment_time": _random_slot(),
            "reason": "MCP API probe test",
        },
    )
    assert "error" not in resp, f"could not schedule a test appointment: {resp}"
    return resp["appointment"]["appointment_id"]


async def test_manageAppointments_list():
    # $ ... manageAppointments '{"action": "list", "start_date": "2026-08-01", \
    #       "end_date_range": "2026-09-30", "facility_ids": "100010000000008157"}'
    resp = await call_tool(
        "manageAppointments",
        {
            "action": "list",
            "start_date": "2026-08-01",
            "end_date_range": "2026-09-30",
            "facility_ids": FACILITY_ID,
        },
    )
    assert "error" not in resp


async def test_manageAppointments_schedule():
    # $ ... manageAppointments '{"action": "schedule", "patient_id": "100010000000018023", \
    #       "provider_id": "100010000000000117", "facility_id": "100010000000008157", \
    #       "appointment_date": "2026-09-20", "appointment_time": "09:00 AM", \
    #       "reason": "MCP API probe test"}'
    resp = await call_tool(
        "manageAppointments",
        {
            "action": "schedule",
            "patient_id": PATIENT_ID,
            "provider_id": PROVIDER_ID,
            "facility_id": FACILITY_ID,
            "appointment_date": _random_date(),
            "appointment_time": _random_slot(),
            "reason": "MCP API probe test",
        },
    )
    assert "error" not in resp
    assert resp.get("appointment", {}).get("appointment_id")


async def test_manageAppointments_reschedule_autofill():
    # $ ... manageAppointments '{"action": "reschedule", "appointment_id": "<fresh appointment_id>", \
    #       "appointment_date": "2026-09-21", "appointment_time": "10:00 AM"}'
    #
    # FIXED BUG (2026-09-02): the auto-fill path (appointment_id alone, relying on
    # the tool's own documented behavior to backfill patient_id/facility_id/
    # provider_id from the existing appointment) used to fail with "Missing
    # required fields for rescheduling". Root cause: GET /appointment/{id}'s
    # response uses "patient_id", but the auto-fill code looked for
    # "practice_patient_id" (a field name that only exists on the RESCHEDULE
    # POST response, not this GET). Fixed in scheduling_tools.py.
    appointment_id = await _schedule_appointment()
    resp = await call_tool(
        "manageAppointments",
        {
            "action": "reschedule",
            "appointment_id": appointment_id,
            "appointment_date": _random_date(),
            "appointment_time": _random_slot(),
        },
    )
    assert "error" not in resp
    assert resp.get("code") == "0"


async def test_manageAppointments_reschedule_explicit_fields():
    # $ ... manageAppointments '{"action": "reschedule", "appointment_id": "<fresh appointment_id>", \
    #       "appointment_date": "2026-09-21", "appointment_time": "10:00 AM", \
    #       "patient_id": "100010000000018023", "provider_id": "100010000000000117", \
    #       "facility_id": "100010000000008157"}'
    appointment_id = await _schedule_appointment()
    resp = await call_tool(
        "manageAppointments",
        {
            "action": "reschedule",
            "appointment_id": appointment_id,
            "appointment_date": _random_date(),
            "appointment_time": _random_slot(),
            "patient_id": PATIENT_ID,
            "provider_id": PROVIDER_ID,
            "facility_id": FACILITY_ID,
        },
    )
    assert "error" not in resp
    assert resp.get("code") == "0"


async def test_manageAppointments_cancel():
    # $ ... manageAppointments '{"action": "cancel", "appointment_id": "<fresh appointment_id>", \
    #       "cancel_reason": "MCP API probe test cleanup"}'
    appointment_id = await _schedule_appointment()
    resp = await call_tool(
        "manageAppointments",
        {
            "action": "cancel",
            "appointment_id": appointment_id,
            "cancel_reason": "MCP API probe test cleanup",
        },
    )
    assert "error" not in resp
