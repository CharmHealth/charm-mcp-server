"""Tests for manageReferrals (create/list/get/update/respond, direction="out"|"in").

Fakes CharmHealthAPIClient so no real network/API access is needed — same
pattern as test_billing.py. Particular focus on things confirmed live against
a real sandbox (see docs/ch-733-progress.md), most recently (2026-08-11):

1. list's response-wrapper key is "referralout"/"referralin", not "referrals".
2. get's response is nested one level under "referral_out"/"referral_in"
   (plus "code"/"message" at the top), not flat — this silently broke
   update's fetch-then-merge (every `existing.get(...)` returned None) and
   was misdiagnosed as a stale MCP server for a while before being traced to
   this actual unwrapping bug.
3. create/update/respond's response is nested TWO levels under
   "referrals"/"referrals" — and, separately, its own party-member fields
   (from_member/to_internal_member/etc.) are NOT reliable confirmation of
   what got persisted (confirmed live: sent ...117, that response said
   ...110, an immediate GET correctly showed ...117 stored). This tool now
   re-fetches via "get" after a successful create/update/respond and returns
   THAT as the authoritative result, falling back to the raw (unwrapped)
   mutation response only if the verify-fetch itself fails.
4. referral_notes/response_notes are raw internal file pointers, not the
   text sent — masked rather than surfaced as content. Note: the verify-GET
   success path never surfaces either field at all (the real "get" entity
   doesn't return them), so masking is now primarily exercised via the
   fallback path (verify-GET fails, falls back to the raw mutation response,
   which DOES include them).
5. response_status's valid set genuinely differs per (direction, action) —
   validated client-side against a confirmed map, not a single shared enum.

"delete" was deliberately removed (deleteReferralOut throws an uncaught NPE
server-side for any referral with no internal-member party — no client-side
workaround), so there's nothing to test for it.
"""

from __future__ import annotations

import datetime
import json

import pytest
from fastmcp.exceptions import ToolError

from tools import referrals


class _FakeAPIClient:
    """Stands in for CharmHealthAPIClient — returns canned responses keyed
    by exact endpoint string, per HTTP method.

    A get_responses/post_responses/put_responses value may be a single dict
    (always returned for that endpoint) or a list of dicts (consumed in
    order across successive calls to that same endpoint, last one repeating
    once exhausted) — the list form is what lets a test simulate "the first
    GET to this endpoint succeeds, a later GET to the SAME endpoint fails",
    needed for update's pre-fetch-then-verify-fetch pattern.
    """

    def __init__(self, get_responses=None, post_responses=None, put_responses=None):
        self._get = get_responses or {}
        self._post = post_responses or {}
        self._put = put_responses or {}
        self._get_counts: dict[str, int] = {}
        self.get_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, dict]] = []
        self.put_calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        self.get_calls.append((endpoint, params or {}))
        responses = self._get[endpoint]
        if isinstance(responses, list):
            idx = min(self._get_counts.get(endpoint, 0), len(responses) - 1)
            self._get_counts[endpoint] = idx + 1
            return responses[idx]
        return responses

    async def post(self, endpoint, data=None, params=None):
        self.post_calls.append((endpoint, data or params or {}))
        return self._post[endpoint]

    async def put(self, endpoint, data=None, params=None):
        self.put_calls.append((endpoint, data or {}))
        return self._put[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(referrals, "CharmHealthAPIClient", lambda **kwargs: fake_client)


def _get_out(fields: dict) -> dict:
    """The real shape of GET /referrals/out/{id} — fields nested under "referral_out"."""
    return {"code": "0", "message": "success", "referral_out": fields}


def _get_in(fields: dict) -> dict:
    """The real shape of GET /referrals/in/{id} — fields nested under "referral_in"."""
    return {"code": "0", "message": "success", "referral_in": fields}


def _mutation(fields: dict, message: str = "success") -> dict:
    """The real shape of create/update/respond's own response — fields
    double-nested under "referrals"/"referrals"."""
    return {"code": "0", "message": message, "referrals": {"referrals": fields}}


# ── _unwrap_get_response / _unwrap_mutation_response ────────────────────


def test_unwrap_get_response_extracts_nested_fields() -> None:
    wrapped = _get_out({"ref_id": "999", "patient_id": "p1"})
    assert referrals._unwrap_get_response(wrapped, "out") == {"ref_id": "999", "patient_id": "p1"}


def test_unwrap_get_response_falls_back_on_unexpected_shape() -> None:
    """If the wrapper key isn't present (e.g. an error dict slipped through),
    return the input unchanged rather than crashing or losing the error."""
    flat = {"error": "something else"}
    assert referrals._unwrap_get_response(flat, "out") == flat


def test_unwrap_mutation_response_extracts_double_nested_fields() -> None:
    wrapped = _mutation({"ref_id": "999", "priority": "Urgent"})
    assert referrals._unwrap_mutation_response(wrapped) == {"ref_id": "999", "priority": "Urgent"}


def test_unwrap_mutation_response_falls_back_on_unexpected_shape() -> None:
    flat = {"ref_id": "999"}
    assert referrals._unwrap_mutation_response(flat) == flat


# ── create ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_out_trusts_verify_get_over_mutation_echo(monkeypatch) -> None:
    """The create response's own party-member fields are NOT reliable —
    confirmed live (sent ...117, response echoed ...110, a follow-up GET
    correctly showed ...117 persisted). The tool must return the verify-GET's
    data, not the raw create response's."""
    fake = _FakeAPIClient(
        post_responses={
            "/referrals/out": _mutation({"ref_id": "999", "from_member": "110"}),  # unreliable echo
        },
        get_responses={
            "/referrals/out/999": _get_out({"ref_id": "999", "from_member_id": "117"}),  # authoritative
        },
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="create", direction="out",
        facility_id="f1", referral_date=datetime.date(2026, 8, 6),
        from_member="117", to_internal_member="2", patient_id="p1",
    )

    assert result["ref_id"] == "999"
    assert result["from_member_id"] == "117"
    assert "ref_id=999" in result["guidance"]


@pytest.mark.asyncio
async def test_create_falls_back_to_mutation_response_if_verify_get_fails(monkeypatch) -> None:
    fake = _FakeAPIClient(
        post_responses={"/referrals/out": _mutation({"ref_id": "999", "priority": "Normal"})},
        get_responses={"/referrals/out/999": {"error": "simulated verify failure"}},
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="create", direction="out",
        facility_id="f1", referral_date=datetime.date(2026, 8, 6),
        from_member="1", to_internal_member="2",
    )

    assert result["ref_id"] == "999"
    assert result["priority"] == "Normal"


@pytest.mark.asyncio
async def test_create_out_missing_facility_or_date_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="create", direction="out", from_member="1", to_internal_member="2",
        )

    assert "facility_id and referral_date" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_out_missing_from_member_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="create", direction="out",
            facility_id="f1", referral_date=datetime.date(2026, 8, 6), to_internal_member="2",
        )

    assert "from_member" in json.loads(str(exc_info.value))["error"]


@pytest.mark.asyncio
async def test_create_out_requires_a_receiving_party(monkeypatch) -> None:
    """Neither to_external_member nor to_internal_member provided — must fail
    before ever calling the API, not send a half-formed referral."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="create", direction="out",
            facility_id="f1", referral_date=datetime.date(2026, 8, 6), from_member="1",
        )

    assert "to_external_member or to_internal_member" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_in_requires_to_member_and_a_sending_party(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="create", direction="in",
            facility_id="f1", referral_date=datetime.date(2026, 8, 6),
        )

    assert "to_member" in json.loads(str(exc_info.value))["error"]


@pytest.mark.asyncio
async def test_create_response_masks_raw_notes_pointer_on_verify_fallback(monkeypatch) -> None:
    """REFERRAL_NOTES is a raw DFS file-pointer server-side — confirmed live
    with a garbled value. The real "get" entity never returns referral_notes
    at all, so this is only reachable via the verify-GET-fails fallback path
    (which returns the raw mutation response) — must still mask it there."""
    fake = _FakeAPIClient(
        post_responses={
            "/referrals/out": _mutation({
                "ref_id": "999",
                "referral_notes": "1786019884879_referral.html!@>NN1:-4152206861348658358",
            }),
        },
        get_responses={"/referrals/out/999": {"error": "simulated verify failure"}},
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="create", direction="out",
        facility_id="f1", referral_date=datetime.date(2026, 8, 6),
        from_member="1", to_internal_member="2",
        referral_notes="Please see patient for follow-up.",
    )

    assert result.get("referral_notes") is None
    assert "internal file pointer" in result["_notes_fields_note"]


@pytest.mark.asyncio
async def test_create_diagnoses_accepts_stringified_json(monkeypatch) -> None:
    """LLMs sometimes stringify array-typed params — diagnoses/insurance must
    accept a JSON-encoded string, not just a native list."""
    fake = _FakeAPIClient(
        post_responses={"/referrals/out": _mutation({"ref_id": "999"})},
        get_responses={"/referrals/out/999": _get_out({"ref_id": "999"})},
    )
    _patch_client(monkeypatch, fake)

    await referrals.manageReferrals.fn(
        action="create", direction="out",
        facility_id="f1", referral_date=datetime.date(2026, 8, 6),
        from_member="1", to_internal_member="2",
        diagnoses=json.dumps([{"name": "Hypertension", "code": "I10"}]),
    )

    _, sent_body = fake.post_calls[0]
    assert sent_body["diagnoses"] == [{"name": "Hypertension", "code": "I10"}]


@pytest.mark.asyncio
async def test_create_diagnoses_rejects_malformed_json_string(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="create", direction="out",
            facility_id="f1", referral_date=datetime.date(2026, 8, 6),
            from_member="1", to_internal_member="2",
            diagnoses="not valid json{",
        )

    assert "diagnoses" in json.loads(str(exc_info.value))["error"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_create_out_rejects_to_be_reviewed(monkeypatch) -> None:
    """"To Be Reviewed" is respond/out's set, not create's — create/update/out
    use Pending|Received|Reviewed."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="create", direction="out",
            facility_id="f1", referral_date=datetime.date(2026, 8, 6),
            from_member="1", to_internal_member="2",
            response_status="To Be Reviewed",
        )

    assert "Received" in json.loads(str(exc_info.value))["guidance"]
    assert fake.post_calls == []


# ── list ───────────────────────────────────────────────────────────────
# Confirmed live: the real response wraps the array under a key matching the
# outer XML tag name in EntityXMLFormat.xml ("referralout"/"referralin"),
# not "referrals" — this was a real bug (always returned empty) until fixed.


@pytest.mark.asyncio
async def test_list_out_reads_the_real_wrapper_key(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/referrals/out": {"referralout": [{"ref_id": "1"}, {"ref_id": "2"}]},
    })
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(action="list", direction="out")

    assert result["total_count"] == 2
    assert "2 referral(s)" in result["guidance"]


@pytest.mark.asyncio
async def test_list_in_reads_the_real_wrapper_key(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/referrals/in": {"referralin": [{"ref_id": "1"}]},
    })
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(action="list", direction="in")

    assert result["total_count"] == 1


@pytest.mark.asyncio
async def test_list_no_results_reports_correctly(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={"/referrals/out": {"referralout": []}})
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(action="list", direction="out")

    assert result["total_count"] == 0
    assert "No referrals found" in result["guidance"]


@pytest.mark.asyncio
async def test_list_out_filter_params_use_confirmed_names(monkeypatch) -> None:
    """Confirmed directly against CharmTemplateHandler's criteria-resolver
    code — from_member_id/to_internal_member_id/to_external_member_id, not
    the create-body field names (from_member/to_internal_member/...)."""
    fake = _FakeAPIClient(get_responses={"/referrals/out": {"referralout": []}})
    _patch_client(monkeypatch, fake)

    await referrals.manageReferrals.fn(
        action="list", direction="out",
        from_member="1", to_internal_member="2", to_external_member="3",
        patient_id="p1", facility_id="f1", response_status="Pending",
    )

    _, sent_params = fake.get_calls[0]
    assert sent_params == {
        "patient_id": "p1", "facility_id": "f1", "response_status": "Pending",
        "from_member_id": "1", "to_internal_member_id": "2", "to_external_member_id": "3",
    }


@pytest.mark.asyncio
async def test_list_in_filter_params_use_confirmed_names(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={"/referrals/in": {"referralin": []}})
    _patch_client(monkeypatch, fake)

    await referrals.manageReferrals.fn(
        action="list", direction="in",
        to_member="1", from_internal_member="2", from_external_member="3",
    )

    _, sent_params = fake.get_calls[0]
    assert sent_params == {
        "to_member_id": "1", "from_internal_member_id": "2", "from_external_member_id": "3",
    }


@pytest.mark.asyncio
async def test_list_rejects_response_status_invalid_for_this_direction(monkeypatch) -> None:
    """"Completed" is valid for direction="in" but not direction="out" (out's list set is
    Pending/Reviewed/To Be Reviewed). Previously this validation was never run for "list"
    at all — the invalid filter went straight to the API's query params, which would
    silently produce a misleading empty result instead of a clear error."""
    fake = _FakeAPIClient(get_responses={"/referrals/out": {"referralout": []}})
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="list", direction="out", response_status="Completed",
        )

    assert "response_status" in json.loads(str(exc_info.value))["error"]
    assert fake.get_calls == []


# ── get ────────────────────────────────────────────────────────────────
# CONFIRMED LIVE (2026-08-11): the response is NOT flat — fields nest one
# level under "referral_out"/"referral_in", alongside "code"/"message".


@pytest.mark.asyncio
async def test_get_out_unwraps_nested_fields(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/referrals/out/999": _get_out({"ref_id": "999", "patient_id": "p1"}),
    })
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(action="get", direction="out", referral_id="999")

    assert result["ref_id"] == "999"
    assert result["patient_id"] == "p1"
    assert result["guidance"] == "Referral retrieved."
    assert "code" not in result and "message" not in result


@pytest.mark.asyncio
async def test_get_in_unwraps_nested_fields(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/referrals/in/500": _get_in({"ref_in_id": "500", "patient_id": "p1"}),
    })
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(action="get", direction="in", referral_id="500")

    assert result["ref_in_id"] == "500"


@pytest.mark.asyncio
async def test_get_missing_referral_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(action="get", direction="out")

    assert json.loads(str(exc_info.value))["error"] == "referral_id required for get"


# ── update ─────────────────────────────────────────────────────────────
# The real backend does a full row overwrite, not a partial patch (confirmed
# live: omitting to_internal_member wiped it to null). update fetches the
# existing referral first (unwrapping get's nesting — the actual root cause
# of "update needs undocumented fields", previously misdiagnosed as staleness)
# and merges caller-supplied fields on top of it, then re-fetches afterward
# for an authoritative result rather than trusting the PUT response's body.


@pytest.mark.asyncio
async def test_update_out_merges_omitted_fields_from_existing_record(monkeypatch) -> None:
    fake = _FakeAPIClient(
        get_responses={
            "/referrals/out/999": _get_out({
                "ref_id": "999", "patient_id": "p1", "facility_id": "f1",
                "from_member_id": "1", "to_internal_member_id": "2",
                "referral_date": "2026-08-06",
                "priority": "Normal", "referral_reason": "Follow-up",
                "response_status": "Pending",
            }),
        },
        put_responses={"/referrals/out/999": _mutation({"ref_id": "999"})},
    )
    _patch_client(monkeypatch, fake)

    # Caller only wants to change priority — everything else should be
    # pulled from the existing record, not sent as null/omitted.
    await referrals.manageReferrals.fn(
        action="update", direction="out", referral_id="999", priority="Urgent",
    )

    _, sent_body = fake.put_calls[0]
    assert sent_body["priority"] == "Urgent"
    assert sent_body["facility_id"] == "f1"
    assert sent_body["from_member"] == "1"
    assert sent_body["to_internal_member"] == "2"
    assert sent_body["patient_id"] == "p1"
    assert sent_body["referral_reason"] == "Follow-up"
    assert sent_body["response_status"] == "Pending"


@pytest.mark.asyncio
async def test_update_out_drops_response_status_invalid_for_update_from_merge(monkeypatch) -> None:
    """The existing referral's response_status ("To Be Reviewed") was set by a prior
    respond() call — valid for direction="out" action="respond", but NOT in update's own
    narrower set (Pending/Received/Reviewed). The caller only wants to change priority and
    never touched response_status — merging the existing value in unvalidated would send a
    value update's own schema rejects, failing over a field the caller didn't ask about.
    Must be dropped from the outgoing body instead."""
    fake = _FakeAPIClient(
        get_responses={
            "/referrals/out/999": _get_out({
                "ref_id": "999", "patient_id": "p1", "facility_id": "f1",
                "from_member_id": "1", "to_internal_member_id": "2",
                "referral_date": "2026-08-06", "priority": "Normal",
                "response_status": "To Be Reviewed",
            }),
        },
        put_responses={"/referrals/out/999": _mutation({"ref_id": "999"})},
    )
    _patch_client(monkeypatch, fake)

    await referrals.manageReferrals.fn(
        action="update", direction="out", referral_id="999", priority="Urgent",
    )

    _, sent_body = fake.put_calls[0]
    assert sent_body["priority"] == "Urgent"
    assert "response_status" not in sent_body


@pytest.mark.asyncio
async def test_update_in_drops_response_status_invalid_for_update_from_merge(monkeypatch) -> None:
    """Same fix, direction="in": "Completed" is valid for create/respond but not for
    update's own set (Pending/Received/Reviewed)."""
    fake = _FakeAPIClient(
        get_responses={
            "/referrals/in/999": _get_in({
                "ref_in_id": "999", "patient_id": "p1", "facility_id": "f1",
                "to_member_id": "1", "referral_date": "2026-08-06",
                "response_status": "Completed",
            }),
        },
        put_responses={"/referrals/in/999": _mutation({"ref_in_id": "999"})},
    )
    _patch_client(monkeypatch, fake)

    await referrals.manageReferrals.fn(
        action="update", direction="in", referral_id="999", priority="Urgent",
    )

    _, sent_body = fake.put_calls[0]
    assert "response_status" not in sent_body


@pytest.mark.asyncio
async def test_update_out_fails_cleanly_if_required_fields_absent_everywhere(monkeypatch) -> None:
    """facility_id/from_member/patient_id are read with a bare .asLong() and
    no null check server-side — omitting them throws an opaque 500. If the
    merge can't fill them in from the existing record either, fail before
    ever calling PUT."""
    fake = _FakeAPIClient(get_responses={"/referrals/out/999": _get_out({"ref_id": "999"})})
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(action="update", direction="out", referral_id="999")

    assert "facility_id, from_member, and patient_id" in json.loads(str(exc_info.value))["error"]
    assert fake.put_calls == []


@pytest.mark.asyncio
async def test_update_fails_cleanly_if_referral_date_absent_everywhere(monkeypatch) -> None:
    """updateReferralJSON/updateReferralInJSON both declare referral_date
    min-occurrences="1" — schema-required on both directions, independent of
    the facility_id/from_member/patient_id check above. Must fail before
    calling PUT if the merge can't backfill it either."""
    fake = _FakeAPIClient(get_responses={
        "/referrals/out/999": _get_out({"ref_id": "999", "facility_id": "f1", "from_member_id": "1", "patient_id": "p1"}),
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(action="update", direction="out", referral_id="999")

    assert "referral_date" in json.loads(str(exc_info.value))["error"]
    assert fake.put_calls == []


@pytest.mark.asyncio
async def test_update_in_fails_cleanly_if_facility_id_absent_everywhere(monkeypatch) -> None:
    """facility_id is schema-required for 'in' update too, despite having no
    effect on the row — must fail before calling PUT if unfillable."""
    fake = _FakeAPIClient(get_responses={
        "/referrals/in/500": _get_in({"ref_in_id": "500", "patient_id": "p1", "referral_date": "2026-08-01"}),
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(action="update", direction="in", referral_id="500")

    assert "facility_id" in json.loads(str(exc_info.value))["error"]
    assert fake.put_calls == []


@pytest.mark.asyncio
async def test_update_in_ignores_facility_id_value_but_still_requires_it_present(monkeypatch) -> None:
    """updateReferralIn's facility_id read is dead code server-side (has zero
    effect on the row) but the API's request SCHEMA still requires the key to
    be present (min-occurrences="1") — a field can be schema-required without
    the business logic ever using its value. Same for referral_date on both
    directions. The merge fills both from the existing record automatically."""
    fake = _FakeAPIClient(
        get_responses={"/referrals/in/500": _get_in({
            "ref_in_id": "500", "patient_id": "p1", "facility_id": "f1",
            "referral_date": "2026-08-01",
        })},
        put_responses={"/referrals/in/500": _mutation({"ref_in_id": "500"})},
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="update", direction="in", referral_id="500", priority="Urgent",
    )

    assert result["guidance"] == "Referral updated."
    _, sent_body = fake.put_calls[0]
    assert sent_body["patient_id"] == "p1"
    assert sent_body["facility_id"] == "f1"
    assert sent_body["referral_date"] == "2026-08-01"
    assert sent_body["priority"] == "Urgent"


@pytest.mark.asyncio
async def test_update_fails_if_fetching_existing_record_errors(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/referrals/out/999": {"error": "HTTP 404: not found"},
    })
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="update", direction="out", referral_id="999",
            facility_id="f1", from_member="1", patient_id="p1",
        )

    assert "Could not fetch the existing referral" in json.loads(str(exc_info.value))["guidance"]
    assert fake.put_calls == []


@pytest.mark.asyncio
async def test_update_trusts_verify_get_over_put_response_echo(monkeypatch) -> None:
    """Same unreliable-echo issue as create — CONFIRMED LIVE a PUT that left
    from_member unchanged at ...117 echoed back ...110 in its own response; an
    immediate GET correctly showed ...117 still persisted. update must return
    the verify-GET's data, not the PUT response's."""
    fake = _FakeAPIClient(
        get_responses={
            "/referrals/out/999": [
                _get_out({  # pre-update existing-record fetch
                    "ref_id": "999", "patient_id": "p1", "facility_id": "f1",
                    "from_member_id": "117", "referral_date": "2026-08-01",
                }),
                _get_out({  # post-update verify fetch — authoritative
                    "ref_id": "999", "patient_id": "p1", "facility_id": "f1",
                    "from_member_id": "117", "referral_date": "2026-08-01", "priority": "Urgent",
                }),
            ],
        },
        put_responses={
            "/referrals/out/999": _mutation({"ref_id": "999", "from_member": "110"}),  # unreliable echo
        },
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="update", direction="out", referral_id="999", priority="Urgent",
    )

    assert result["from_member_id"] == "117"
    assert result["priority"] == "Urgent"


@pytest.mark.asyncio
async def test_update_success_path_does_not_surface_notes_fields_at_all(monkeypatch) -> None:
    """When the post-update verify-GET succeeds (the normal case), the result
    reflects "get"'s real shape, which never includes referral_notes/
    response_notes at all — no garbling, no masking note needed, they're
    just absent."""
    fake = _FakeAPIClient(
        get_responses={
            "/referrals/out/999": _get_out({
                "ref_id": "999", "patient_id": "p1", "facility_id": "f1",
                "from_member_id": "1", "referral_date": "2026-08-01", "priority": "Urgent",
            }),
        },
        put_responses={"/referrals/out/999": _mutation({"ref_id": "999"})},
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="update", direction="out", referral_id="999", priority="Urgent",
    )

    assert "referral_notes" not in result
    assert "_notes_fields_note" not in result
    assert result["priority"] == "Urgent"


@pytest.mark.asyncio
async def test_update_response_masks_raw_notes_pointer_on_verify_fallback(monkeypatch) -> None:
    """Fallback path: the pre-update existing-record fetch succeeds (needed to
    pass validation), but the post-update verify-fetch fails, so this falls
    back to the raw PUT response — which DOES include referral_notes — and
    that raw value must still be masked."""
    fake = _FakeAPIClient(
        get_responses={
            "/referrals/out/999": [
                _get_out({
                    "ref_id": "999", "patient_id": "p1", "facility_id": "f1",
                    "from_member_id": "1", "referral_date": "2026-08-01",
                }),
                {"error": "simulated verify failure"},
            ],
        },
        put_responses={
            "/referrals/out/999": _mutation({
                "ref_id": "999",
                "referral_notes": "1786019884879_referral.html!@>NN1:-4152206861348658358",
            }),
        },
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="update", direction="out", referral_id="999", priority="Urgent",
    )

    assert result.get("referral_notes") is None
    assert "internal file pointer" in result["_notes_fields_note"]


@pytest.mark.asyncio
async def test_update_missing_referral_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(action="update", direction="out")

    assert json.loads(str(exc_info.value))["error"] == "referral_id required for update"
    assert fake.get_calls == []


@pytest.mark.asyncio
async def test_update_in_rejects_completed(monkeypatch) -> None:
    """update/in's real set is Pending|Received|Reviewed, NOT Pending|Completed
    like create/respond use for "in" — confirmed against updateReferralInJSON's
    own schema, documented as found rather than assumed consistent."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="update", direction="in", referral_id="500", response_status="Completed",
        )

    error_payload = json.loads(str(exc_info.value))
    assert "not valid" in error_payload["error"]
    assert "Received" in error_payload["guidance"]
    assert fake.get_calls == []  # fails before ever fetching the existing record


# ── respond ────────────────────────────────────────────────────────────
# facility_id is confirmed REQUIRED for respond on both directions — enforced
# by a request-level JSON-schema layer (security-api-referral.xml's
# <jsontemplate name="addReferralResponseJSON"/"addReferralInResponseJSON">,
# both declaring facility_id min-occurrences="1") that's separate from, and
# invisible in, ReferralBeanImpl.addReferralResponse/addReferralInResponse's
# Java body (which never reads facility_id at all). Found live: the API
# rejected a real call with "Mandatory parameters missing: facility_id" even
# though every field the Java method itself uses was present.
#
# NOTE (2026-08-11): live-testing found `respond` currently returns a generic
# HTTP 500 on BOTH directions, on multiple different valid pre-existing
# referrals — looks like a backend-side issue in that environment, not
# something these tests (or any client-side fix) can address. The happy-path
# tests below describe the INTENDED behavior once that's resolved.


@pytest.mark.asyncio
async def test_respond_out_trusts_verify_get_and_sends_correct_body(monkeypatch) -> None:
    fake = _FakeAPIClient(
        post_responses={
            "/referrals/out/999/response": _mutation({"ref_id": "999", "response_status": "Pending"}),
        },
        get_responses={
            "/referrals/out/999": _get_out({"ref_id": "999", "response_status": "Reviewed"}),
        },
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="respond", direction="out", referral_id="999", facility_id="f1",
        response_date=datetime.date(2026, 8, 7),
        response_notes="Patient seen, no further action needed.",
        response_status="Reviewed",
    )

    endpoint, sent_body = fake.post_calls[0]
    assert endpoint == "/referrals/out/999/response"
    assert sent_body == {
        "facility_id": "f1",
        "response_date": "2026-08-07",
        "response_notes": "Patient seen, no further action needed.",
        "response_status": "Reviewed",
    }
    assert result["response_status"] == "Reviewed"
    assert result["guidance"] == "Response recorded."


@pytest.mark.asyncio
async def test_respond_missing_facility_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="respond", direction="out", referral_id="999", response_status="Reviewed",
        )

    assert json.loads(str(exc_info.value))["error"] == "facility_id required for respond"
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_respond_out_does_not_send_diagnoses(monkeypatch) -> None:
    """addReferralResponse (out) never reads diagnoses at all — only
    addReferralInResponse writes RESPONSE_DIAGNOSES. Sending it for "out"
    would be silently ignored server-side, so don't send it."""
    fake = _FakeAPIClient(
        post_responses={"/referrals/out/999/response": _mutation({"ref_id": "999"})},
        get_responses={"/referrals/out/999": _get_out({"ref_id": "999"})},
    )
    _patch_client(monkeypatch, fake)

    await referrals.manageReferrals.fn(
        action="respond", direction="out", referral_id="999", facility_id="f1",
        response_status="Reviewed",
        diagnoses=[{"name": "Hypertension", "code": "I10"}],
    )

    _, sent_body = fake.post_calls[0]
    assert "diagnoses" not in sent_body


@pytest.mark.asyncio
async def test_respond_in_sends_diagnoses_and_notes_cascade_quirk(monkeypatch) -> None:
    fake = _FakeAPIClient(
        post_responses={"/referrals/in/500/response": _mutation({"ref_in_id": "500"})},
        get_responses={"/referrals/in/500": _get_in({"ref_in_id": "500"})},
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="respond", direction="in", referral_id="500", facility_id="f1",
        response_status="Completed",
        diagnoses=[{"name": "Hypertension", "code": "I10"}],
    )

    _, sent_body = fake.post_calls[0]
    assert sent_body["diagnoses"] == [{"name": "Hypertension", "code": "I10"}]
    # The real backend cascades response_date/response_notes onto a linked
    # internal outbound record and force-sets ITS status to "To Be Reviewed"
    # regardless of what was passed here — the guidance must warn about this
    # so a caller doesn't assume only the "in" record changed.
    assert "To Be Reviewed" in result["guidance"]


@pytest.mark.asyncio
async def test_respond_missing_referral_id_returns_clean_error(monkeypatch) -> None:
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(action="respond", direction="out")

    assert json.loads(str(exc_info.value))["error"] == "referral_id required for respond"
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_respond_no_content_returns_clean_error(monkeypatch) -> None:
    """facility_id alone isn't a response — must still require real content."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="respond", direction="out", referral_id="999", facility_id="f1",
        )

    assert json.loads(str(exc_info.value))["error"] == "No response content provided"
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_respond_response_masks_raw_notes_pointer_on_verify_fallback(monkeypatch) -> None:
    """RESPONSE_NOTES uses the same raw-file-pointer storage as
    REFERRAL_NOTES — only reachable via the verify-GET-fails fallback path
    (the real "get" entity never returns response_notes either)."""
    fake = _FakeAPIClient(
        post_responses={
            "/referrals/out/999/response": _mutation({
                "ref_id": "999",
                "response_notes": "1786019884879_response.html!@>NN1:-4152206861348658358",
            }),
        },
        get_responses={"/referrals/out/999": {"error": "simulated verify failure"}},
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="respond", direction="out", referral_id="999", facility_id="f1",
        response_notes="Patient seen, cleared for surgery.",
    )

    assert result.get("response_notes") is None
    assert "internal file pointer" in result["_notes_fields_note"]


# ── response_status validation ──────────────────────────────────────────
# The valid set genuinely differs per (direction, action) — confirmed against
# security-api-referral.xml's <jsontemplate> regexes. Validated client-side so
# an invalid value gets a helpful error instead of the API's generic
# "HTTP 400: Invalid value passed for response_status".


@pytest.mark.asyncio
async def test_respond_out_rejects_received_lists_valid_values(monkeypatch) -> None:
    """"Received" is valid for create/update/out but NOT for respond/out —
    respond's own set is Pending|To Be Reviewed|Reviewed."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="respond", direction="out", referral_id="999", facility_id="f1",
            response_status="Received",
        )

    error_payload = json.loads(str(exc_info.value))
    assert "not valid" in error_payload["error"]
    assert "To Be Reviewed" in error_payload["guidance"]
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_respond_out_accepts_to_be_reviewed(monkeypatch) -> None:
    fake = _FakeAPIClient(
        post_responses={"/referrals/out/999/response": _mutation({"ref_id": "999"})},
        get_responses={"/referrals/out/999": _get_out({"ref_id": "999"})},
    )
    _patch_client(monkeypatch, fake)

    result = await referrals.manageReferrals.fn(
        action="respond", direction="out", referral_id="999", facility_id="f1",
        response_status="To Be Reviewed",
    )

    assert result["guidance"] == "Response recorded."


@pytest.mark.asyncio
async def test_respond_in_rejects_reviewed(monkeypatch) -> None:
    """respond/in's set is Pending|Completed — "Reviewed" (valid for out) isn't."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await referrals.manageReferrals.fn(
            action="respond", direction="in", referral_id="500", facility_id="f1",
            response_status="Reviewed",
        )

    assert "Pending" in json.loads(str(exc_info.value))["guidance"]
    assert fake.post_calls == []
