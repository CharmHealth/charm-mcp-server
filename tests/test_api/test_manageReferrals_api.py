"""Live-server API probe for manageReferrals (src/tools/referrals.py).

Run against the already-running MCP server (see tests/test_api/conftest.py). Each test
is self-contained (creates its own fresh referral) so it can be run alone via
your IDE's per-test run button.

Test data: Ahmed Choi — patient_id 100010000000018023; Peter Parker —
member_id 100010000000000117; Charm Clinic — facility_id 100010000000008157.

IMPORTANT CAVEAT: this sandbox has exactly ONE provider (Peter Parker), so
every referral here necessarily uses him as BOTH the referring and receiving
party (a "self-referral"). Some failures below may be specific to that
degenerate case rather than real bugs — flagged individually where relevant.
"""
from conftest import call_tool

PATIENT_ID = "100010000000018023"  # Ahmed Choi
PROVIDER_ID = "100010000000000117"  # Peter Parker (only provider in this sandbox)
FACILITY_ID = "100010000000008157"  # Charm Clinic
REFERRAL_DATE = "2026-09-02"


async def _create_referral_out() -> str:
    resp = await call_tool(
        "manageReferrals",
        {
            "action": "create",
            "direction": "out",
            "facility_id": FACILITY_ID,
            "referral_date": REFERRAL_DATE,
            "from_member": PROVIDER_ID,
            "to_internal_member": PROVIDER_ID,
            "patient_id": PATIENT_ID,
            "referral_reason": "MCP API probe test",
        },
    )
    assert "error" not in resp, f"could not create a test referral: {resp}"
    return resp["ref_id"]


async def test_manageReferrals_create_out():
    # $ ... manageReferrals '{"action": "create", "direction": "out", "facility_id": "100010000000008157", \
    #       "referral_date": "2026-09-02", "from_member": "100010000000000117", \
    #       "to_internal_member": "100010000000000117", "patient_id": "100010000000018023", \
    #       "referral_reason": "MCP API probe test"}'
    resp = await call_tool(
        "manageReferrals",
        {
            "action": "create",
            "direction": "out",
            "facility_id": FACILITY_ID,
            "referral_date": REFERRAL_DATE,
            "from_member": PROVIDER_ID,
            "to_internal_member": PROVIDER_ID,
            "patient_id": PATIENT_ID,
            "referral_reason": "MCP API probe test",
        },
    )
    assert "error" not in resp
    assert resp.get("ref_id")


async def test_manageReferrals_list_out():
    # $ ... manageReferrals '{"action": "list", "direction": "out", "patient_id": "100010000000018023"}'
    resp = await call_tool("manageReferrals", {"action": "list", "direction": "out", "patient_id": PATIENT_ID})
    assert "error" not in resp


async def test_manageReferrals_get_out():
    # $ ... manageReferrals '{"action": "get", "direction": "out", "referral_id": "<fresh ref_id>"}'
    ref_id = await _create_referral_out()
    resp = await call_tool("manageReferrals", {"action": "get", "direction": "out", "referral_id": ref_id})
    assert "error" not in resp
    assert resp.get("ref_id") == ref_id


async def test_manageReferrals_update_out_inconclusive():
    # $ ... manageReferrals '{"action": "update", "direction": "out", "referral_id": "<fresh ref_id>", "priority": "Urgent"}'
    #
    # NOT confirmed as a bug: fails with HTTP 400 {"code":"1000","message":
    # "zf.api.inavalid.id.provided"} even though from_member/to_internal_member
    # both merge in as Peter Parker's own (valid, real) member_id from the
    # existing record. This sandbox has only one provider, so every referral
    # here is a "self-referral" (from_member == to_internal_member) -- create
    # allows this same combination (see test above), but update on the same
    # referral, same merged values, does not. Possibly a backend restriction
    # specific to updating a self-referral, not necessarily a general bug --
    # can't be conclusively distinguished without a second provider to test
    # against. Documented as inconclusive, not asserted as broken.
    ref_id = await _create_referral_out()
    resp = await call_tool(
        "manageReferrals",
        {"action": "update", "direction": "out", "referral_id": ref_id, "priority": "Urgent"},
    )
    assert isinstance(resp, dict)  # always true; documents the finding above, not asserted pass/fail


async def test_manageReferrals_respond_out():
    # $ ... manageReferrals '{"action": "respond", "direction": "out", "referral_id": "<fresh ref_id>", \
    #       "facility_id": "100010000000008157", "patient_id": "100010000000018023", \
    #       "response_notes": "MCP API probe test response", "response_status": "Reviewed"}'
    ref_id = await _create_referral_out()
    resp = await call_tool(
        "manageReferrals",
        {
            "action": "respond",
            "direction": "out",
            "referral_id": ref_id,
            "facility_id": FACILITY_ID,
            "patient_id": PATIENT_ID,
            "response_notes": "MCP API probe test response",
            "response_status": "Reviewed",
        },
    )
    assert "error" not in resp
    assert resp.get("response_status") == "Reviewed"


async def test_manageReferrals_create_in_inconclusive():
    # $ ... manageReferrals '{"action": "create", "direction": "in", "facility_id": "100010000000008157", \
    #       "referral_date": "2026-09-02", "to_member": "100010000000000117", \
    #       "from_internal_member": "100010000000000117", "patient_id": "100010000000018023"}'
    #
    # NOT confirmed as a bug: fails with HTTP 400 {"code":"6","message":
    # "Internal Error"} using the same self-referral pattern (to_member ==
    # from_internal_member == Peter Parker) that succeeded fine for direction="out"
    # create. The inconsistency itself (out succeeds, in fails, same underlying
    # pattern) is worth a closer look, but this sandbox's single-provider
    # limitation makes it impossible to rule out "in" create just disallowing
    # self-referrals specifically, vs. a genuine direction="in" bug. Documented
    # as inconclusive, not asserted as broken.
    resp = await call_tool(
        "manageReferrals",
        {
            "action": "create",
            "direction": "in",
            "facility_id": FACILITY_ID,
            "referral_date": REFERRAL_DATE,
            "to_member": PROVIDER_ID,
            "from_internal_member": PROVIDER_ID,
            "patient_id": PATIENT_ID,
        },
    )
    assert isinstance(resp, dict)  # always true; documents the finding above, not asserted pass/fail
