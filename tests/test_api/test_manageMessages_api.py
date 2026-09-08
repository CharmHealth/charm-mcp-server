"""Live-server API probe for manageMessages (src/tools/communication.py).

Run against the already-running MCP server (see tests/test_api/conftest.py).

Test data: Ahmed Choi — patient_id 100010000000018023; Charm Clinic —
facility_id 100010000000008157.

Note: send(secure) and send(sms) below assert the SPECIFIC expected error,
not success -- those are real, correct backend rejections given this test
patient's actual data (no PHR/portal account, no bidirectional SMS enabled
for this sandbox practice), not bugs. send(whatsapp) is different: it's a
confirmed likely code bug (wrong endpoint path), asserted as CORRECT
(should-succeed) behavior so it goes green once fixed.
"""
from conftest import call_tool, TEST_DATA

PATIENT_ID = TEST_DATA["patient_id"]
FACILITY_ID = TEST_DATA["facility_id"]


async def test_manageMessages_get_thread():
    # $ ... manageMessages '{"action": "get_thread", "patient_id": "100010000000018023"}'
    resp = await call_tool("manageMessages", {"action": "get_thread", "patient_id": PATIENT_ID})
    assert "error" not in resp


async def test_manageMessages_list():
    # $ ... manageMessages '{"action": "list"}'
    resp = await call_tool("manageMessages", {"action": "list"})
    assert "error" not in resp


async def test_manageMessages_send_secure_rejected_no_phr_account():
    # $ ... manageMessages '{"action": "send", "patient_id": "100010000000018023", \
    #       "content": "...", "channel": "secure", "facility_id": "100010000000008157"}'
    #
    # Correct rejection, not a bug: Ahmed Choi has no PHR/portal account, and
    # secure messages require one. The tool's guidance correctly identifies this.
    resp = await call_tool(
        "manageMessages",
        {
            "action": "send",
            "patient_id": PATIENT_ID,
            "content": "MCP API probe test message - secure channel",
            "channel": "secure",
            "facility_id": FACILITY_ID,
        },
    )
    assert "error" in resp
    assert "PHR account is mandatory" in resp["error"]


async def test_manageMessages_send_sms_rejected_not_enabled():
    # $ ... manageMessages '{"action": "send", "patient_id": "100010000000018023", \
    #       "content": "...", "channel": "sms", "facility_id": "100010000000008157"}'
    #
    # Correct rejection, not a bug: this sandbox practice doesn't have
    # bidirectional SMS enabled (a real practice-level config limitation).
    resp = await call_tool(
        "manageMessages",
        {
            "action": "send",
            "patient_id": PATIENT_ID,
            "content": "MCP API probe test message - sms channel",
            "channel": "sms",
            "facility_id": FACILITY_ID,
        },
    )
    assert "error" in resp
    assert "Bidirectional sms is not enabled" in resp["error"]


async def test_manageMessages_send_whatsapp():
    # $ ... manageMessages '{"action": "send", "patient_id": "100010000000018023", \
    #       "content": "...", "channel": "whatsapp", "facility_id": "100010000000008157"}'
    #
    # CONFIRMED LIKELY BUG: fails with HTTP 404 {"code":5,"message":"Invalid URL
    # Passed"} -- CharmHealth's own "no such route" error, not a business-rule
    # rejection like the secure/sms tests above. `_send_whatsapp()` posts to
    # "/messages/whatsapp/patient/{patient_id}/send" -- this path likely doesn't
    # exist under /api/ehr/v1 on the real backend. Same failure signature as
    # manageFax's "send" and "status" (see test_manageFax_api.py) -- possibly a
    # shared root cause (WhatsApp/fax may live under a different, unsupported
    # API base path entirely). Written for CORRECT behavior so it goes green
    # once the real endpoint is confirmed and fixed.
    resp = await call_tool(
        "manageMessages",
        {
            "action": "send",
            "patient_id": PATIENT_ID,
            "content": "MCP API probe test message - whatsapp channel",
            "channel": "whatsapp",
            "facility_id": FACILITY_ID,
        },
    )
    assert "error" not in resp, f"whatsapp send still broken (Invalid URL Passed): {resp}"
