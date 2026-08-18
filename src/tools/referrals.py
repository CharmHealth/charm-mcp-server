from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import date
from api import CharmHealthAPIClient
from common.utils import strip_empty_values
import json
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

referrals_mcp = FastMCP(name="CharmHealth Referrals MCP Server")


def _unwrap_get_response(response: Any, direction: str) -> Dict[str, Any]:
    """
    CONFIRMED LIVE (2026-08-11): GET /referrals/{direction}/{id} does NOT return
    the referral's fields flat at the top level — it wraps them one level down
    under a key matching the direction ("referral_out"/"referral_in"), alongside
    "code"/"message":
        {"code": "0", "message": "success", "referral_out": {...actual fields...}}
    Every earlier version of this tool assumed a flat shape (matching
    ReferralOutResponseNew/ReferralInResponseNew's XML definition, which is a
    non-array entity — wrongly inferred to mean "serializes flat"). This silently
    broke `update`'s fetch-then-merge: `existing.get("facility_id")` always
    returned None because `facility_id` was actually at `existing["referral_out"]
    ["facility_id"]`, so the merge never worked and every field it claimed to
    backfill had to be supplied explicitly — exactly the "undocumented required
    fields" behavior reported live, repeatedly, and previously misdiagnosed as a
    stale MCP server rather than a real bug in this unwrapping.
    """
    if not isinstance(response, dict):
        return response
    key = "referral_out" if direction == "out" else "referral_in"
    inner = response.get(key)
    return inner if isinstance(inner, dict) else response


def _unwrap_mutation_response(response: Any) -> Dict[str, Any]:
    """
    CONFIRMED LIVE (2026-08-11): create/update/respond's response is wrapped
    TWO levels deep, not flat — {"code", "message", "referrals": {"referrals":
    {...actual fields...}}} — confirmed against both ReferralOutResponse's and
    ReferralInResponse's real XML definition (<referrals name="...">
    <referrals table="...">...</referrals></referrals>, a double-nested tag of
    the same name) and a live create/update call. `ref_id` extraction
    (`response.get("ref_id")`) was silently always None before this fix.

    Separately and more importantly: this response's own from_member/
    to_internal_member/to_member/from_internal_member/from_external_member
    fields are NOT reliable confirmation of what was persisted — confirmed live
    by sending from_member=...117 and getting back "...110" in this same
    response, then immediately re-fetching via GET (whose fields ARE reliable,
    per _unwrap_get_response) and finding ...117 correctly stored. Callers of
    this unwrap function should still do a follow-up GET for anything beyond
    the bare ref_id — don't trust the unwrapped party-member fields either.
    """
    if not isinstance(response, dict):
        return response
    outer = response.get("referrals")
    if isinstance(outer, dict):
        inner = outer.get("referrals")
        if isinstance(inner, dict):
            return inner
    return response


def _mask_notes_pointer(resp: Dict[str, Any]) -> Dict[str, Any]:
    """
    REFERRAL_NOTES and RESPONSE_NOTES are both stored server-side as raw DFS
    file-pointer strings, not the text that was sent. Confirmed live for
    referral_notes (garbled values like
    "1786019884879_referral.html!@>NN1:-4152206861348658358"); confirmed for
    response_notes by reading the identical file-storage code path in
    ReferralBeanImpl.addReferralResponse/addReferralInResponse — same write
    pattern, same garbling on read. Reading either back as real text requires
    the separate GET .../notes sub-resource, which this tool doesn't implement
    yet. Strip both rather than hand an LLM a string that looks like content
    but isn't.
    """
    if not isinstance(resp, dict):
        return resp
    masked_any = False
    for field in ("referral_notes", "response_notes"):
        if resp.get(field):
            resp[field] = None
            masked_any = True
    if masked_any:
        resp["_notes_fields_note"] = (
            "referral_notes/response_notes omitted from this response — the API returns "
            "an internal file pointer here, not the text you sent. Reading actual note "
            "content requires the /notes sub-resource, not yet supported by this tool."
        )
    return resp


def _parse_list_of_dicts(value: Optional[Union[str, List[Dict[str, Any]]]], field_name: str) -> Optional[List[Dict[str, Any]]]:
    """LLMs sometimes stringify array-typed params — accept either a native list or a JSON-encoded string."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError(f"{field_name} must be a JSON array of objects, or a valid JSON-encoded string of one")
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of objects")
    return value


# response_status's valid set genuinely differs per (direction, action) — confirmed
# directly against security-api-referral.xml's <jsontemplate> regexes, each checked
# individually rather than assumed consistent (they aren't, even within one
# direction — see REFERRAL_STATUS_SETS["out"]["update"] vs. ["out"]["respond"]).
# Kept as plain str (not Literal) in the function signature because a single
# Literal type can't vary by direction/action — validated here instead, with an
# error that actually lists the valid options rather than passing through the
# real API's generic "Invalid value passed for response_status" 400.
REFERRAL_STATUS_SETS: Dict[str, Dict[str, tuple]] = {
    "out": {
        "create": ("Pending", "Received", "Reviewed"),
        "update": ("Pending", "Received", "Reviewed"),
        "respond": ("Pending", "To Be Reviewed", "Reviewed"),
        "list": ("Pending", "Reviewed", "To Be Reviewed"),
    },
    "in": {
        "create": ("Pending", "Completed"),
        # NOT "Pending"|"Completed" like create/respond — updateReferralInJSON's
        # own schema declares this set; inconsistent within the real API itself,
        # documented as found rather than smoothed over.
        "update": ("Pending", "Received", "Reviewed"),
        "respond": ("Pending", "Completed"),
        "list": ("Pending", "Completed"),
    },
}


def _validate_response_status(direction: str, action: str, response_status: Optional[str]) -> Optional[Dict[str, Any]]:
    """Returns an error dict if response_status is set but invalid for this
    (direction, action); None if absent or valid."""
    if response_status is None:
        return None
    valid = REFERRAL_STATUS_SETS[direction][action]
    if response_status not in valid:
        return {
            "error": f"response_status={response_status!r} is not valid for direction={direction!r} action={action!r}",
            "guidance": f"Valid values here are: {', '.join(valid)}."
        }
    return None


@referrals_mcp.tool
@with_tool_metrics()
async def manageReferrals(
    action: Literal["create", "list", "get", "update", "respond"],
    direction: Literal["out", "in"],

    referral_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    facility_id: Optional[str] = None,
    referral_date: Optional[date] = None,
    response_date: Optional[date] = None,

    # direction="out": referring this practice's patient TO another provider
    from_member: Optional[str] = None,
    to_external_member: Optional[str] = None,
    to_internal_member: Optional[str] = None,

    # direction="in": tracking a referral received FROM another provider
    to_member: Optional[str] = None,
    from_external_member: Optional[str] = None,
    from_internal_member: Optional[str] = None,

    priority: Optional[Literal["Urgent", "Normal"]] = None,
    referral_reason: Optional[str] = None,
    referral_notes: Optional[str] = None,
    response_notes: Optional[str] = None,
    response_status: Optional[str] = None,
    encounter_id: Optional[str] = None,

    diagnoses: Optional[Union[str, List[Dict[str, Any]]]] = None,
    insurance: Optional[Union[str, List[Dict[str, Any]]]] = None,

    chartnote_ids: Optional[str] = None,
    lab_ids: Optional[str] = None,
    document_ids: Optional[str] = None,
    image_ids: Optional[str] = None,
    growth_ids: Optional[str] = None,

    page: Optional[int] = None,
    per_page: Optional[int] = None,

    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient referrals — referring a patient out to a specialist, or tracking
    a referral received from another provider.

    <usecase>
    Referral coordination: create/list/get/update referrals in either direction, and
    record a response to one (e.g. the specialist's findings, or your own review of an
    incoming referral). E-signing and file attachments are not covered by this tool
    yet. Creating a referral is NOT the same as sending it — see the transmission
    note below.
    </usecase>

    <instructions>
    direction picks which referral family this call operates on — the two are separate
    records on the backend, not two views of the same thing:
    - "out": referring this practice's patient TO another provider (a specialist).
      Party fields: from_member (the referring provider, at this practice, required on
      create) plus exactly one of to_external_member (outside specialist) or
      to_internal_member (in-network provider) — required on create.
    - "in": tracking a referral this practice received FROM another provider.
      Party fields: to_member (the receiving provider, at this practice, required on
      create) plus exactly one of from_external_member or from_internal_member —
      required on create.

    Actions:
    - "create": New referral. Requires facility_id, referral_date, and the direction's
      required party fields above.
    - "list": List referrals for this direction. Optional filters: patient_id,
      facility_id, response_status, page, per_page, plus the direction's party-id
      fields (from_member/to_internal_member/to_external_member for "out";
      to_member/from_internal_member/from_external_member for "in") to filter by
      provider.
    - "get": Fetch a single referral (referral_id required).
    - "update": Update an existing referral (referral_id required). The real backend
      does a FULL ROW OVERWRITE, not a partial patch — any field you omit gets wiped
      to null/empty server-side. This tool fetches the existing referral first and
      merges your fields on top of it, so omitting facility_id/patient_id/priority/
      referral_reason/response_status/referral_date/the party fields will correctly
      preserve their current values. facility_id, from_member (or to_member for
      "in"), and patient_id are still hard-required by the backend either way —
      the merge fills them from the existing record if you don't pass them.
      NOT covered by this merge (still wiped if omitted, because "get" doesn't
      return them or their round-trip shape isn't confirmed): referral_notes,
      response_notes, related_encounter_id (encounter_id), diagnoses, insurance,
      and the attachment-linking *_ids fields. Pass these explicitly every time
      you want them to survive an update.
      direction="in" additionally cannot change facility_id or its party fields
      via update at all — the backend ignores them for "in" regardless.
    - "respond": Record a response to a referral (referral_id AND facility_id both
      required — facility_id is enforced by the API's request schema even though
      the response-recording logic itself never uses it, so don't assume it's
      optional just because "get"/"update" treat it as re-derivable). Beyond that,
      provide at least one of response_date, response_notes, response_status, or
      (direction="in" only) diagnoses. chartnote_ids/lab_ids/document_ids/
      image_ids/growth_ids link supporting records to the response, same
      comma-separated-id convention as create/update. direction="out" does NOT
      accept diagnoses — the API's schema has no such field for it; only
      direction="in" writes a response diagnosis list.
      QUIRK (direction="in" only): if this incoming referral is linked to an
      internal outbound referral record (i.e. it was auto-created when someone at
      this practice referred a patient to an internal provider), responding here
      ALSO cascades response_date/response_notes onto that linked "out" record and
      force-sets ITS response_status to the literal string "To Be Reviewed" —
      regardless of the response_status you passed on this call. Real backend
      behavior, not a bug in this tool.
      Both directions auto-notify the original referring provider in-app when a
      response is recorded (unless they're the one responding).

    KNOWN LIMITATION — external-provider referrals: to_external_member (direction="out")
    and from_external_member (direction="in") must be a real, pre-existing numeric ID
    already registered in this practice's referral directory. There is no tool here (or
    any REST endpoint found in the backend) to look up or register a new external
    provider — passing a name or an arbitrary/unregistered number fails with
    "zf.api.inavalid.id.provided". Only to_internal_member/from_internal_member
    (in-network providers, already known to this practice) are reliably usable end to
    end today.

    KNOWN LIMITATION — creating a referral does not send it, for external referrals.
    An internal referral (to_internal_member/from_internal_member) auto-notifies the
    receiving provider in-app at creation time — nothing more to do. An EXTERNAL
    referral notifies no one on creation; the real EHR requires a separate manual
    "Transmit" step (fax, or Direct Secure Messaging via an accredited HISP) that
    exists only in the old UI layer and has no REST API equivalent at all — there is
    no way for this tool (or any API caller) to actually send an external referral to
    the specialist. Combined with the directory-lookup gap above, external referrals
    are effectively metadata-only today: don't tell a user or clinician an external
    referral has been "sent" just because create succeeded.

    response_status valid values — CONFIRMED PER (direction, action) from the API's
    own request schemas (security-api-referral.xml jsontemplates), each checked
    individually rather than assumed consistent — they are NOT consistent, even
    within the same direction, even though every action writes the same
    RESPONSE_STATUS column:
    - direction="out", action="create": "Pending" | "Received" | "Reviewed".
    - direction="out", action="update": "Pending" | "Received" | "Reviewed" (same as create).
    - direction="out", action="respond": "Pending" | "To Be Reviewed" | "Reviewed"
      — "Received" is NOT valid here, "To Be Reviewed" IS (the inverse of
      create/update's set on those two values).
    - direction="out", "list" filter: "Pending" | "Reviewed" | "To Be Reviewed".
    - direction="in", action="create": "Pending" | "Completed".
    - direction="in", action="update": "Pending" | "Received" | "Reviewed" — NOT
      "Completed". Surprising given create/respond both use Pending|Completed for
      "in", but this is what the API's own updateReferralInJSON schema declares;
      documented as found, not smoothed over for consistency.
    - direction="in", action="respond": "Pending" | "Completed".

    diagnoses / insurance accept either a native JSON array of objects or a
    JSON-encoded string of one, e.g. diagnoses=[{"name": "...", "code": "...", "id": "..."}]
    or insurance=[{"name": "...", "id": "..."}].

    chartnote_ids / lab_ids / document_ids / image_ids / growth_ids are comma-separated
    id strings (e.g. "123,456"), matching the real API's expected format.

    When required parameters are missing, ask the user to provide the specific values
    rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    access_token = None
    refresh_token = None
    base_url = None
    token_url = None
    client_secret = None
    accounts_server = None

    try:
        headers = get_http_headers()
        access_token = headers.get('x-user-access-token')
        refresh_token = headers.get('x-user-refresh-token')
        base_url = headers.get('x-charmhealth-base-url')
        token_url = headers.get('x-charmhealth-token-url')
        client_secret = headers.get('x-charmhealth-client-secret')
        accounts_server = headers.get('x-charmhealth-accounts-server')

        if accounts_server:
            token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"

        if base_url and not base_url.endswith('/api/ehr/v1'):
            base_url = base_url.rstrip('/') + '/api/ehr/v1'

        if access_token:
            logger.info("manageReferrals using user credentials")
        else:
            logger.info("manageReferrals using environment variable credentials")
    except Exception as e:
        logger.debug(f"Could not get HTTP headers (might be stdio mode): {e}")

    async with CharmHealthAPIClient(
        access_token=access_token,
        refresh_token=refresh_token,
        base_url=base_url,
        token_url=token_url,
        client_secret=client_secret
    ) as client:
        try:
            base_path = f"/referrals/{direction}"

            try:
                diagnoses_parsed = _parse_list_of_dicts(diagnoses, "diagnoses")
                insurance_parsed = _parse_list_of_dicts(insurance, "insurance")
            except ValueError as e:
                return {"error": str(e), "guidance": "Fix the field and try again."}

            def build_body() -> Dict[str, Any]:
                body: Dict[str, Any] = {
                    "facility_id": facility_id,
                    "referral_date": referral_date.isoformat() if referral_date else None,
                    "patient_id": patient_id,
                    "priority": priority,
                    "referral_reason": referral_reason,
                    "referral_notes": referral_notes,
                    "response_notes": response_notes,
                    "response_status": response_status,
                    "encounter_id": encounter_id,
                    "diagnoses": diagnoses_parsed,
                    "insurance": insurance_parsed,
                    "chartnote_ids": chartnote_ids,
                    "lab_ids": lab_ids,
                    "document_ids": document_ids,
                    "image_ids": image_ids,
                    "growth_ids": growth_ids,
                }
                if direction == "out":
                    body["from_member"] = from_member
                    body["to_external_member"] = to_external_member
                    body["to_internal_member"] = to_internal_member
                else:
                    body["to_member"] = to_member
                    body["from_external_member"] = from_external_member
                    body["from_internal_member"] = from_internal_member
                return {k: v for k, v in body.items() if v is not None}

            match action:

                case "create":
                    status_error = _validate_response_status(direction, "create", response_status)
                    if status_error:
                        return status_error
                    if not facility_id or not referral_date:
                        return {
                            "error": "facility_id and referral_date are required to create a referral",
                            "guidance": "Provide facility_id and referral_date (YYYY-MM-DD)."
                        }
                    if direction == "out":
                        if not from_member:
                            return {
                                "error": "from_member is required for direction='out'",
                                "guidance": "Provide from_member (the referring provider at this practice)."
                            }
                        if not to_external_member and not to_internal_member:
                            return {
                                "error": "One of to_external_member or to_internal_member is required for direction='out'",
                                "guidance": "Provide the receiving provider — to_external_member for an outside specialist, to_internal_member for someone in-network."
                            }
                    else:
                        if not to_member:
                            return {
                                "error": "to_member is required for direction='in'",
                                "guidance": "Provide to_member (the receiving provider at this practice)."
                            }
                        if not from_external_member and not from_internal_member:
                            return {
                                "error": "One of from_external_member or from_internal_member is required for direction='in'",
                                "guidance": "Provide the referring provider — from_external_member for an outside provider, from_internal_member for someone in-network."
                            }

                    response = await client.post(base_path, data=build_body())
                    if isinstance(response, dict) and response.get("error"):
                        return {
                            "error": response["error"],
                            "guidance": "Could not create the referral. Verify facility_id, referral_date, and the required party fields for this direction."
                        }
                    # CONFIRMED LIVE (2026-08-11): this response is double-nested
                    # ({"referrals":{"referrals":{...}}}) — response.get("ref_id") was
                    # silently always None before this fix, hence "ref_id=None" in every
                    # prior create's guidance message. Unwrap to get the real ref_id.
                    created = _unwrap_mutation_response(response)
                    # _unwrap_mutation_response falls back to returning `response`
                    # unchanged when it isn't shaped as expected — which itself falls
                    # back to whatever the API sent if that wasn't a dict either (e.g.
                    # an array). Guard here so a create that actually succeeded doesn't
                    # get reported as a failure just because we can't parse ref_id out
                    # of it — that false failure is worse than a missing ref_id, since
                    # the natural response to "Could not create" is a retry, which
                    # would duplicate the referral that was, in fact, created.
                    if not isinstance(created, dict):
                        created = {"raw_response": created}
                    ref_id = created.get("ref_id") or created.get("ref_in_id")
                    # Don't trust this response's own party-member fields (from_member/
                    # to_internal_member/etc.) — CONFIRMED LIVE they can echo back a
                    # different value than what was actually persisted (sent ...117, this
                    # response said ...110, a follow-up GET correctly showed ...117 stored).
                    # Re-fetch instead of returning `created` directly.
                    if ref_id:
                        verify_response = await client.get(f"{base_path}/{ref_id}")
                        if isinstance(verify_response, dict) and not verify_response.get("error"):
                            created = _unwrap_get_response(verify_response, direction)
                    created["guidance"] = (
                        f"Referral created (ref_id={ref_id}). Use 'get' with this referral_id to check status, "
                        "or 'update' to add diagnoses/notes later."
                    )
                    return strip_empty_values(_mask_notes_pointer(created))

                case "list":
                    status_error = _validate_response_status(direction, "list", response_status)
                    if status_error:
                        return status_error
                    params: Dict[str, Any] = {}
                    if patient_id:
                        params["patient_id"] = patient_id
                    if facility_id:
                        params["facility_id"] = facility_id
                    if response_status:
                        params["response_status"] = response_status
                    if page:
                        params["page"] = page
                    if per_page:
                        params["per_page"] = per_page
                    # Confirmed directly against the backend's criteria-resolver code
                    # (CharmTemplateHandler: REFERRAL_FROM_MEMBER_CR / REFERRAL_TO_MEMBER_CR
                    # for "out"; REFERRAL_IN_TO_MEMBER_CR / REFERRAL_IN_FROM_MEMBER_CR for "in") —
                    # both directions' filter param names below are real, not guessed.
                    # NOTE: facility_id has no effect on direction="in" — GetReferralInListSQ's
                    # WHERE clause doesn't include a facility criteria macro at all, unlike "out".
                    if direction == "out":
                        if from_member:
                            params["from_member_id"] = from_member
                        if to_internal_member:
                            params["to_internal_member_id"] = to_internal_member
                        if to_external_member:
                            params["to_external_member_id"] = to_external_member
                    else:
                        if to_member:
                            params["to_member_id"] = to_member
                        if from_internal_member:
                            params["from_internal_member_id"] = from_internal_member
                        if from_external_member:
                            params["from_external_member_id"] = from_external_member

                    response = await client.get(base_path, params=params)
                    if isinstance(response, dict) and response.get("error"):
                        return {
                            "error": response["error"],
                            "guidance": "Could not list referrals. Verify the filters provided."
                        }
                    # The real response wraps the array under a key matching the outer XML
                    # element name in EntityXMLFormat.xml — "referralout" for direction="out"
                    # (<referralout name="ReferralsOutResponseNew" classAttr="array">) and
                    # "referralin" for direction="in" — NOT "referrals". Confirmed by reading
                    # the backend's own entity-format config, not guessed.
                    wrapper_key = "referralout" if direction == "out" else "referralin"
                    referrals = response if isinstance(response, list) else response.get(wrapper_key, [])
                    referrals = [_mask_notes_pointer(r) for r in referrals]
                    result: Dict[str, Any] = {"referrals": referrals, "total_count": len(referrals)}
                    result["guidance"] = (
                        f"Found {len(referrals)} referral(s)." if referrals
                        else "No referrals found matching the filters."
                    )
                    return strip_empty_values(result)

                case "get":
                    if not referral_id:
                        return {
                            "error": "referral_id required for get",
                            "guidance": "Provide the referral_id to fetch."
                        }
                    response = await client.get(f"{base_path}/{referral_id}")
                    if isinstance(response, dict) and response.get("error"):
                        return {
                            "error": response["error"],
                            "guidance": "Could not retrieve the referral. Verify referral_id and direction are correct."
                        }
                    result = _unwrap_get_response(response, direction)
                    result["guidance"] = "Referral retrieved."
                    return strip_empty_values(_mask_notes_pointer(result))

                case "update":
                    if not referral_id:
                        return {
                            "error": "referral_id required for update",
                            "guidance": "Provide the referral_id to update."
                        }
                    # Validate a caller-supplied value up front. A value merged in from
                    # the existing record below is NOT necessarily valid for "update" —
                    # it may have been set by a different action's schema (e.g. "respond"
                    # accepts "To Be Reviewed" on direction="out", which "update" does not;
                    # "create"/"respond" accept "Completed" on direction="in", which
                    # "update" does not either) — see REFERRAL_STATUS_SETS. Re-checked
                    # after the merge below, not assumed valid just because some prior
                    # write accepted it. The two directions handle an invalid *merged*
                    # value differently there — "out" fails closed (the field isn't
                    # safe to omit server-side), "in" drops it (safe to omit) — see the
                    # comment at that check.
                    status_error = _validate_response_status(direction, "update", response_status)
                    if status_error:
                        return status_error

                    # The real backend does a FULL ROW OVERWRITE on update, not a partial
                    # patch — confirmed live: omitting to_internal_member on an update wiped
                    # it to null, which was what triggered deleteReferralOut's NPE bug (the
                    # reason "delete" isn't exposed by this tool at all — see the docstring).
                    # Fetch the existing record and merge caller-supplied fields on top of it
                    # so a call that only means to change e.g. priority doesn't silently
                    # blank everything else.
                    #
                    # IMPORTANT — this merge is only as complete as what "get" returns.
                    # ReferralOutResponseNew/ReferralInResponseNew (the "get" shape) does NOT
                    # include referral_notes, response_notes, or related_encounter_id at all,
                    # and diagnoses/insurance's stored round-trip shape (JSON string vs. parsed
                    # array) isn't confirmed — so those fields are NOT safely preserved here.
                    # If you're not explicitly setting one of those on this call, treat it as
                    # being wiped, same as before this fix.
                    existing_raw = await client.get(f"{base_path}/{referral_id}")
                    if isinstance(existing_raw, dict) and existing_raw.get("error"):
                        return {
                            "error": existing_raw["error"],
                            "guidance": "Could not fetch the existing referral to merge before updating. Verify referral_id and direction are correct."
                        }
                    # MUST unwrap — CONFIRMED LIVE this response nests fields under
                    # "referral_out"/"referral_in", not flat. Without this, every
                    # existing.get(...) below silently returns None and the merge never
                    # actually merges anything — this was the real cause of "update
                    # requires undocumented fields", not a stale server as first assumed.
                    existing = _unwrap_get_response(existing_raw, direction)
                    if not isinstance(existing, dict):
                        existing = {}

                    if facility_id is None:
                        facility_id = existing.get("facility_id")
                    if patient_id is None:
                        patient_id = existing.get("patient_id")
                    if priority is None:
                        priority = existing.get("priority")
                    if referral_reason is None:
                        referral_reason = existing.get("referral_reason")
                    if response_status is None:
                        merged_status = existing.get("response_status")
                        if merged_status is not None and merged_status not in REFERRAL_STATUS_SETS[direction]["update"]:
                            # The merged-in value is valid for whatever action last set
                            # it (e.g. "respond") but not for "update"'s own narrower
                            # set (see the comment on the pre-merge validation above).
                            #
                            # direction="out": CONFIRMED against ReferralBeanImpl.
                            # updateReferralOut — resStatus is read from the request
                            # body under a null check, but row.set("RESPONSE_STATUS",
                            # resStatus) runs UNCONDITIONALLY, outside that check. Key
                            # absent means resStatus stays null and the column gets
                            # explicitly nulled — the same shape as the
                            # TO_INTERNAL_MEMBER_ID wipe this whole merge exists to
                            # prevent. Omitting it here would silently clear a field
                            # the caller never touched, worse than the 400 this
                            # replaced. Fail instead and let the caller decide.
                            if direction == "out":
                                return {
                                    "error": f"Stored response_status={merged_status!r} is not valid for direction='out' update",
                                    "guidance": (
                                        f"This referral's response_status was set by a different action (e.g. 'respond') and "
                                        f"can't be carried through 'update' as-is — the backend clears the column when "
                                        f"response_status is left out of an update request, it does not leave it untouched. "
                                        f"Provide an explicit response_status from {REFERRAL_STATUS_SETS[direction]['update']} "
                                        f"to keep or change it as part of this call."
                                    )
                                }
                            # direction="in": updateReferralIn has this same row.set
                            # line commented out server-side — the field is dead here,
                            # so omitting an invalid merged value is safe (the stored
                            # value is left untouched either way), unlike "out".
                            merged_status = None
                        response_status = merged_status
                    if referral_date is None and existing.get("referral_date"):
                        try:
                            referral_date = date.fromisoformat(str(existing["referral_date"])[:10])
                        except ValueError:
                            pass  # leave referral_date unset rather than crash on an unexpected format

                    if direction == "out":
                        if from_member is None:
                            from_member = existing.get("from_member_id")
                        if to_external_member is None:
                            to_external_member = existing.get("to_external_member_id")
                        if to_internal_member is None:
                            to_internal_member = existing.get("to_internal_member_id")
                    else:
                        if to_member is None:
                            to_member = existing.get("to_member_id")
                        if from_external_member is None:
                            from_external_member = existing.get("from_external_member_id")
                        if from_internal_member is None:
                            from_internal_member = existing.get("from_internal_member_id")

                    # Two DIFFERENT layers enforce requirements here, and they don't agree
                    # with each other — checked both directly against
                    # security-api-referral.xml, not assumed from one or the other:
                    # (1) ReferralBeanImpl.updateReferralOut/.updateReferralIn (the business
                    #     logic) reads facility_id/from_member/patient_id with a bare
                    #     .asLong() and NO null check — omitting them throws an uncaught NPE
                    #     (opaque 500). For "in", facility_id/party-field reads are dead code
                    #     (commented out), so they have ZERO effect on the row even though...
                    # (2) ...the REQUEST-LEVEL JSON schema (<jsontemplate name=
                    #     "updateReferralJSON"/"updateReferralInJSON">) separately requires
                    #     facility_id AND referral_date on BOTH directions
                    #     (min-occurrences="1") — a field can be schema-required without the
                    #     business logic ever using its value. Confirmed live: `respond`
                    #     required facility_id the same way despite its own Java method never
                    #     reading it (see that case for the same lesson).
                    # Net: "in" update must still SEND a valid facility_id (schema), even
                    # though changing it has no effect (business logic) — the merge above
                    # supplies it from the existing record either way, so this is normally
                    # transparent; only surfaces if the existing record is missing it.
                    if direction == "out":
                        if not facility_id or not from_member or not patient_id:
                            return {
                                "error": "facility_id, from_member, and patient_id are all required for direction='out' update (even if unchanged) and couldn't be filled in from the existing record",
                                "guidance": "Provide facility_id, from_member, and patient_id explicitly — the backend rejects update calls missing any of these three with an opaque 500, not a validation error."
                            }
                    else:
                        if not patient_id or not facility_id:
                            return {
                                "error": "patient_id and facility_id are both required for direction='in' update (even if unchanged) and couldn't be filled in from the existing record",
                                "guidance": "Provide patient_id and facility_id explicitly. facility_id has no effect on an 'in' record but the API's request schema still requires it to be present."
                            }
                        # to_member/from_external_member/from_internal_member are dead code
                        # in updateReferralIn (commented out server-side) — sending them is
                        # harmless but silently has no effect. Those fields can't be changed
                        # via update for direction="in" at all today.
                    if not referral_date:
                        return {
                            "error": "referral_date is required for update (even if unchanged) and couldn't be filled in from the existing record",
                            "guidance": "Provide referral_date explicitly (YYYY-MM-DD) — required by the API's request schema on both directions."
                        }
                    body = build_body()
                    if not body:
                        return {
                            "error": "No fields provided to update",
                            "guidance": "Provide at least one field to change."
                        }
                    response = await client.put(f"{base_path}/{referral_id}", data=body)
                    if isinstance(response, dict) and response.get("error"):
                        return {
                            "error": response["error"],
                            "guidance": "Could not update the referral. Verify referral_id and the fields provided."
                        }
                    # Same two issues as create: this response is double-nested, AND its
                    # party-member fields are unreliable echoes (CONFIRMED LIVE — a PUT
                    # that changed only priority, with from_member unchanged at ...117,
                    # came back reporting from_member as ...110; an immediate GET
                    # correctly showed ...117 still stored). Re-fetch for the authoritative
                    # result instead of trusting this response's body at all.
                    verify_response = await client.get(f"{base_path}/{referral_id}")
                    if isinstance(verify_response, dict) and not verify_response.get("error"):
                        result = _unwrap_get_response(verify_response, direction)
                    else:
                        result = _unwrap_mutation_response(response)
                    result["guidance"] = "Referral updated."
                    return strip_empty_values(_mask_notes_pointer(result))

                case "respond":
                    if not referral_id:
                        return {
                            "error": "referral_id required for respond",
                            "guidance": "Provide the referral_id to respond to."
                        }
                    status_error = _validate_response_status(direction, "respond", response_status)
                    if status_error:
                        return status_error
                    # CONFIRMED LIVE (2026-08-10): facility_id is required for respond on
                    # BOTH directions. This is NOT visible in ReferralBeanImpl.addReferralResponse/
                    # addReferralInResponse's Java body (which never reads facility_id at all,
                    # which is what the earlier pass of this comment relied on) — it's enforced
                    # by a SEPARATE request-level JSON-schema layer this tool missed originally:
                    # security-api-referral.xml's <jsontemplate name="addReferralResponseJSON">
                    # and <jsontemplate name="addReferralInResponseJSON">, both of which declare
                    # `facility_id` with min-occurrences="1". A field can be schema-required
                    # without the business logic ever using it — don't assume "the Java method
                    # doesn't read X" means "X is optional."
                    if not facility_id:
                        return {
                            "error": "facility_id required for respond",
                            "guidance": "Provide facility_id — required by the API's request schema even though the response-recording logic itself doesn't use it."
                        }

                    # Everything else here IS genuinely optional per the same schema. "out"
                    # doesn't accept diagnoses at all (no <key name="diagnoses"> in
                    # addReferralResponseJSON) — only "in" does — so diagnoses is only sent
                    # for direction="in".
                    respond_body: Dict[str, Any] = {
                        "facility_id": facility_id,
                        "response_date": response_date.isoformat() if response_date else None,
                        "response_notes": response_notes,
                        "response_status": response_status,
                        "chartnote_ids": chartnote_ids,
                        "lab_ids": lab_ids,
                        "document_ids": document_ids,
                        "image_ids": image_ids,
                        "growth_ids": growth_ids,
                    }
                    diagnoses_dropped_for_out = direction == "out" and diagnoses_parsed
                    if direction == "in":
                        respond_body["diagnoses"] = diagnoses_parsed
                    respond_body = {k: v for k, v in respond_body.items() if v is not None}

                    # facility_id alone (required above) isn't "a response" — require at
                    # least one actual content field too.
                    if not any(k != "facility_id" for k in respond_body):
                        return {
                            "error": "No response content provided",
                            "guidance": "Provide at least one of response_date, response_notes, response_status"
                                        + (", diagnoses" if direction == "in" else "") + "."
                        }

                    response = await client.post(f"{base_path}/{referral_id}/response", data=respond_body)
                    if isinstance(response, dict) and response.get("error"):
                        # CONFIRMED LIVE (2026-08-11): this endpoint currently returns a
                        # generic "HTTP 500: Internal Error" for BOTH directions, on
                        # multiple different, valid, pre-existing referral_ids with valid
                        # facility_id/response_status — reproduced twice on direction="out"
                        # alone. This is NOT an ID-mismatch or client-input problem (the
                        # earlier theory below about "in" using the wrong linked id is a
                        # real, separate risk from reading addReferralInResponse's
                        # null-unguarded row dereference, but doesn't explain the "out"
                        # failures) — it currently looks like a broader, backend-side issue
                        # in this environment that no client-side fix here can work around.
                        mismatch_hint = (
                            " If this is a 500 on direction='in' specifically, double-check "
                            "referral_id is really that referral's REF_IN_ID (from a "
                            "direction='in' list/get call) and not its linked referral-out's "
                            "id — they're different numbers even for a referral that started "
                            "as an internal 'out' referral. If it fails on direction='out' too "
                            "with the same generic error, this is likely a backend-side issue, "
                            "not something fixable from this tool." if direction == "in" else
                            " A generic 500 here (not a validation-style 400) on otherwise-valid "
                            "input has been observed to be a backend-side issue, not fixable "
                            "from this tool — confirm with whoever owns the API before assuming "
                            "a client-side mistake."
                        )
                        return {
                            "error": response["error"],
                            "guidance": f"Could not record the response. Verify referral_id is correct.{mismatch_hint}"
                        }
                    # Same unreliable-echo risk as create/update — re-fetch rather than
                    # trust this response's own body.
                    verify_response = await client.get(f"{base_path}/{referral_id}")
                    if isinstance(verify_response, dict) and not verify_response.get("error"):
                        result = _unwrap_get_response(verify_response, direction)
                    else:
                        result = _unwrap_mutation_response(response)
                    guidance = "Response recorded."
                    if diagnoses_dropped_for_out:
                        guidance += (
                            " WARNING: diagnoses was provided but NOT sent — direction='out' "
                            "responses don't support a diagnoses field (the API schema has no "
                            "such key for this direction; only direction='in' does). Nothing "
                            "downstream received these diagnoses from this call."
                        )
                    if direction == "in":
                        # Confirmed in ReferralBeanImpl.addReferralInResponse: if this "in"
                        # record is linked to an internal outbound referral (REF_OUT_ID set),
                        # responding here ALSO cascades response_date/response_notes onto
                        # that linked "out" record and force-sets ITS response_status to the
                        # literal string "To Be Reviewed" — regardless of the response_status
                        # passed on this call. Real backend behavior, not a bug in this tool.
                        guidance += (
                            " Note: if this referral is linked to an internal outbound referral "
                            "record, the backend also force-set that record's response_status "
                            "to 'To Be Reviewed', regardless of the response_status passed here."
                        )
                    result["guidance"] = guidance
                    return strip_empty_values(_mask_notes_pointer(result))

        except Exception as e:
            logger.error(f"Error in manageReferrals: {e}")
            return {
                "error": str(e),
                "guidance": f"Failed to {action} referral (direction={direction}). Verify required fields are correct."
            }
