from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import date, timedelta
from api import CharmHealthAPIClient
from common.utils import strip_empty_values
import json
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

billing_mcp = FastMCP(name="CharmHealth Billing MCP Server")


@billing_mcp.tool
@with_tool_metrics()
async def managePatientBilling(
    action: Literal["get_balance", "list_invoices", "get_receipts", "send_balance_reminder"],
    patient_id: str,

    # Listing fields (list_invoices, get_receipts)
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    per_page: Optional[int] = None,
    page: Optional[int] = None,
    facility_id: Optional[str] = None,   # accepted by get_balance/list_invoices/get_receipts; omit for "all facilities"

    # send_balance_reminder fields
    reminder_message: Optional[str] = None,
    send_via: Optional[Literal["email", "phr", "sms"]] = "email",

    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient billing: balance, invoices, receipts, and balance reminders.

    <usecase>
    Patient-facing billing operations for front-desk and patient-outreach workflows —
    checking what a patient owes, reviewing their invoices and receipts, and sending
    them a reminder about an outstanding balance.
    </usecase>

    <instructions>
    Actions:
    - "get_balance": Get a patient's current balance, including unapplied credit and a
      per-invoice breakdown (requires patient_id).
    - "list_invoices": List a patient's invoices (requires patient_id; optionally filter
      by start_date, end_date, per_page, page).
    - "get_receipts": List a patient's receipts/payments on file (requires patient_id;
      optionally filter by start_date, end_date, per_page, page).
    - "send_balance_reminder": Send the patient a reminder about their outstanding
      balance (requires patient_id). This is a mutation — expect it to be gated for
      confirmation before it sends. send_via picks the delivery channel — "email"
      (default), "phr" (patient portal), or "sms". Exactly one channel is attempted
      per call; call again with a different send_via to try another channel.
      reminder_message becomes the message body sent to the patient.

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
            logger.info("managePatientBilling using user credentials")
        else:
            logger.info("managePatientBilling using environment variable credentials")
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
            match action:

                case "get_balance":
                    if not patient_id:
                        return {
                            "error": "patient_id required for get_balance",
                            "guidance": "Provide the patient_id to check their balance."
                        }

                    # /patients/{id}/billing/balances (the "detail" variant, with a
                    # per-invoice breakdown) returns HTTP 404 "Invalid URL Passed" against
                    # the live sandbox — confirmed with and without facility_id, so it's
                    # not a missing-param issue, the route itself isn't reachable here.
                    # Switched to /patients/{id}/balance (BillingReportsAPI.fetchPatientBalance)
                    # instead — confirmed live. Trade-off: no per-invoice breakdown field
                    # (use list_invoices for that), but it actually works.
                    balance_params: Dict[str, Any] = {}
                    if facility_id:
                        balance_params["facility_id"] = facility_id
                    response = await client.get(
                        f"/patients/{patient_id}/balance",
                        params=balance_params
                    )

                    # Real field, confirmed against BillingReportsAPI.fetchPatientBalance:
                    # "total_balance_due" (plus patient_balance_due/insurance_balance_due).
                    total_due = response.get("total_balance_due")
                    if total_due is not None:
                        response["guidance"] = (
                            f"Patient balance retrieved (total due: {total_due}). "
                            "Use send_balance_reminder to notify the patient, or "
                            "list_invoices for a breakdown of individual invoices. "
                        )
                    elif response.get("error"):
                        response["guidance"] = "Could not retrieve balance. Verify patient_id is correct."
                    else:
                        response["guidance"] = "No outstanding balance found for this patient."

                    return strip_empty_values(response)

                case "list_invoices":
                    if not patient_id:
                        return {
                            "error": "patient_id required for list_invoices",
                            "guidance": "Provide the patient_id to list their invoices."
                        }

                    # Confirmed against InvoicesAPI.fetchInvoices: the real query params are
                    # from_date/to_date (not start_date/end_date), and both are effectively
                    # required — fetchInvoices passes them straight into date-parsing with no
                    # null-safe fallback, so omitting either throws "Mandatory parameters
                    # missing" before any results come back. Defaulting to the trailing year
                    # matches the API's own default assumption (limit_one_year=true).
                    params: Dict[str, Any] = {
                        "patient_id": patient_id,
                        "from_date": (start_date or date.today() - timedelta(days=365)).isoformat(),
                        "to_date": (end_date or date.today()).isoformat(),
                    }
                    if facility_id:
                        params["facility_id"] = facility_id
                    if per_page:
                        params["per_page"] = per_page
                    if page:
                        params["page"] = page

                    # InvoicesAPI.fetchInvoices returns a bare JSON array, not
                    # {"invoices": [...]} — response.get(...) would crash with
                    # AttributeError on every call since a list has no .get().
                    # An error, though, still comes back as a dict ({"error": ...}
                    # from CharmHealthAPIClient's own exception handling).
                    response = await client.get("/invoices", params=params)
                    if isinstance(response, dict) and response.get("error"):
                        return {
                            "error": response["error"],
                            "guidance": "Could not retrieve invoices. Verify patient_id is correct."
                        }
                    invoices = response if isinstance(response, list) else []
                    result: Dict[str, Any] = {"invoices": invoices, "total_count": len(invoices)}

                    if invoices:
                        result["guidance"] = (
                            f"Found {len(invoices)} invoice(s) for this patient. "
                            "Use send_balance_reminder to notify the patient. "
                        )
                    else:
                        result["guidance"] = "No invoices found matching the filters."

                    return strip_empty_values(result)

                case "get_receipts":
                    if not patient_id:
                        return {
                            "error": "patient_id required for get_receipts",
                            "guidance": "Provide the patient_id to list their receipts."
                        }

                    # Same real param names/requiredness as list_invoices — confirmed
                    # against ReceiptsAPI.fetchReceipts's route definition.
                    params = {
                        "patient_id": patient_id,
                        "from_date": (start_date or date.today() - timedelta(days=365)).isoformat(),
                        "to_date": (end_date or date.today()).isoformat(),
                    }
                    if facility_id:
                        params["facility_id"] = facility_id
                    if per_page:
                        params["per_page"] = per_page
                    if page:
                        params["page"] = page

                    # ReceiptsAPI.fetchReceipts also returns a bare JSON array —
                    # same shape as /invoices, same crash risk.
                    response = await client.get("/receipts", params=params)
                    if isinstance(response, dict) and response.get("error"):
                        return {
                            "error": response["error"],
                            "guidance": "Could not retrieve receipts. Verify patient_id is correct."
                        }
                    receipts = response if isinstance(response, list) else []
                    result = {"receipts": receipts, "total_count": len(receipts)}

                    if receipts:
                        result["guidance"] = f"Found {len(receipts)} receipt(s) for this patient."
                    else:
                        result["guidance"] = "No receipts found matching the filters."

                    return strip_empty_values(result)

                case "send_balance_reminder":
                    if not patient_id:
                        return {
                            "error": "patient_id required for send_balance_reminder",
                            "guidance": "Provide the patient_id to send a balance reminder."
                        }

                    # Statement-send endpoint, confirmed with Vibhu: {id} is the
                    # patient_id, not a separately-generated statement_id — there's
                    # no statement-listing/creation step to do first.
                    #
                    # The real API dispatches by *presence* of one of these three
                    # top-level keys — email_configuration/phr_configuration/
                    # text_message_configuration — not a flat "message" field, and
                    # exactly one is sent per call (matching send_via). Everything
                    # else in each channel's config (sender info, locale, practice
                    # details) is filled in automatically server-side; invoices,
                    # send_to_guarantor, and send_payment_link are deliberately
                    # left out here — advanced/RCM-adjacent fields out of scope for
                    # this Receptionist-facing action.
                    _CONFIG_KEY = {
                        "email": "email_configuration",
                        "phr": "phr_configuration",
                        "sms": "text_message_configuration",
                    }
                    _SUCCESS_MODE = {
                        "email": "EMAIL",
                        "phr": "PHR",
                        "sms": "TEXT_MESSAGE",
                    }
                    channel = send_via or "email"
                    channel_config: Dict[str, Any] = {}
                    if reminder_message:
                        channel_config["content"] = reminder_message

                    # Real API binds "send_configuration" as a named request PARAMETER
                    # (<param type="JSONObject">), not a raw JSON body (<inputstream>) —
                    # confirmed against the actual EHR frontend (billing_invoice.js
                    # formSendStatementData), which posts a form field named
                    # "send_configuration" whose value is a JSON string, not a nested
                    # JSON body key. BillingSendStatementManager.sendPatientStatement
                    # then reads email_configuration/phr_configuration/text_message_configuration
                    # out of that parsed object.
                    send_data: Dict[str, Any] = {
                        "send_configuration": json.dumps({_CONFIG_KEY[channel]: channel_config})
                    }

                    response = await client.post_form(
                        f"/billing/statements/{patient_id}/send",
                        data=send_data
                    )

                    successful_modes = response.get("successful_delivery_modes") or []
                    if _SUCCESS_MODE[channel] in successful_modes:
                        response["guidance"] = f"Balance reminder sent to the patient via {channel}."
                    else:
                        response["error"] = f"Sending the balance reminder via {channel} failed."
                        response["guidance"] = (
                            f"Sending the balance reminder via {channel} failed. Verify patient_id is "
                            f"correct and the patient has a valid {channel} contact on file, then try "
                            f"again — optionally with a different send_via."
                        )

                    return strip_empty_values(response)

        except Exception as e:
            logger.error(f"Error in managePatientBilling: {e}")
            return {
                "error": str(e),
                "guidance": f"Failed to {action} for patient billing. Verify patient_id and other "
                            "required fields are correct."
            }


# Place-of-service codes CH-489 documents as legal: 01-62, 65, 71, 72, 81, 99.
_VALID_PLACE_OF_SERVICE = {str(n).zfill(2) for n in range(1, 63)} | {"65", "71", "72", "81", "99"}


@billing_mcp.tool
@with_tool_metrics()
async def manageEncounterProcedures(
    action: Literal["list", "add", "update", "delete"],
    patient_id: str,
    encounter_id: str,

    # add/update fields
    code_id: Optional[str] = None,  # from getPracticeInfo(info_type="procedure_codes")
    item_charge: Optional[float] = None,
    item_quantity: Optional[int] = 1,
    modifier_1: Optional[str] = None,
    modifier_2: Optional[str] = None,
    modifier_3: Optional[str] = None,
    modifier_4: Optional[str] = None,
    place_of_service: Optional[str] = "11",  # default Office, per CH-489 acceptance criteria
    related_diagnosis_ids: Optional[Union[str, List[str]]] = None,  # diagnosis IDs from the encounter — comma-separated string or a native array
    claim_comments: Optional[str] = None,
    skip_invoice_check: Optional[bool] = False,

    # update/delete fields
    consultation_cpt_map_id: Optional[str] = None,

    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Attach, update, remove, or list billing-grade CPT/HCPCS procedures on an encounter.

    <usecase>
    Per-encounter procedure coding — attaching a CPT code (with modifiers, place of service,
    and linked diagnoses) to an encounter so it's billable, not just narrative text in the
    chart note. Look up code_id first with getPracticeInfo(info_type="procedure_codes").
    </usecase>

    <instructions>
    Actions:
    - "list": List procedures already attached to an encounter (requires patient_id, encounter_id).
    - "add": Attach a new procedure to the encounter (requires patient_id, encounter_id, code_id,
      item_charge). item_quantity defaults to 1. place_of_service defaults to "11" (Office) —
      valid values are "01"-"62", "65", "71", "72", "81", "99". modifier_1-4 and
      related_diagnosis_ids (a comma-separated string or a native array of diagnosis IDs)
      is optional.
    - "update": Modify an already-attached procedure (requires patient_id, encounter_id,
      consultation_cpt_map_id — the ID returned by "list"/"add" — plus whichever fields are
      changing).
    - "delete": Remove a procedure from the encounter (requires patient_id, encounter_id,
      consultation_cpt_map_id).

    If an invoice has already been generated for this encounter, add/update is rejected —
    the response will say so. Pass skip_invoice_check=True only if the caller explicitly
    intends to modify billed procedures after invoicing.

    When required parameters are missing, ask the user to provide the specific values rather
    than proceeding with defaults or auto-generated values.
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
            logger.info("manageEncounterProcedures using user credentials")
        else:
            logger.info("manageEncounterProcedures using environment variable credentials")
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
            match action:

                case "list":
                    if not patient_id or not encounter_id:
                        return {
                            "error": "patient_id and encounter_id required for list",
                            "guidance": "Provide both patient_id and encounter_id to list procedures on the encounter."
                        }

                    # GET /patients/{pid}/encounters/{eid}/procedures (InvoicesAPI.getCPTsForEncounter)
                    # — confirmed against APIRequestByGet.xml + InvoicesAPIUtil.fetchCPTsForEncounterInJSON.
                    response = await client.get(f"/patients/{patient_id}/encounters/{encounter_id}/procedures")
                    if isinstance(response, dict) and response.get("error"):
                        return {
                            "error": response["error"],
                            "guidance": "Could not list procedures. Verify patient_id and encounter_id are correct."
                        }
                    procedures = response.get("procedures") or []
                    result = {"procedures": procedures, "total_count": len(procedures)}

                    if procedures:
                        result["guidance"] = f"Found {len(procedures)} procedure(s) on this encounter. Use consultation_cpt_map_id with action='update' or 'delete'."
                    else:
                        result["guidance"] = "No procedures attached to this encounter yet. Use action='add' with a code_id from getPracticeInfo(info_type='procedure_codes')."

                    return strip_empty_values(result)

                case "add" | "update":
                    if not patient_id or not encounter_id:
                        return {
                            "error": "patient_id and encounter_id required",
                            "guidance": f"Provide both patient_id and encounter_id to {action} a procedure."
                        }
                    if action == "add" and not code_id:
                        return {
                            "error": "code_id required for add",
                            "guidance": "Look up code_id with getPracticeInfo(info_type='procedure_codes'), then retry."
                        }
                    if action == "add" and item_charge is None:
                        return {
                            "error": "item_charge required for add",
                            "guidance": "Provide item_charge (the practice's real API requires it explicitly — it does not fall back to the catalog's default charge)."
                        }
                    if action == "update" and not consultation_cpt_map_id:
                        return {
                            "error": "consultation_cpt_map_id required for update",
                            "guidance": "Use action='list' first to find the consultation_cpt_map_id of the procedure to update."
                        }
                    pos = place_of_service or "11"
                    if pos not in _VALID_PLACE_OF_SERVICE:
                        return {
                            "error": f"Invalid place_of_service: {pos}",
                            "guidance": "place_of_service must be one of \"01\"-\"62\", \"65\", \"71\", \"72\", \"81\", \"99\"."
                        }

                    # Accept a native array directly (e.g. diagnosis IDs fetched from
                    # manageDiagnoses(action='list')) or a JSON-encoded array string,
                    # falling back to the documented comma-separated string. Callers
                    # sending a native list against a str-only param get rejected at
                    # the protocol layer before this code ever runs — same pitfall
                    # as create_template's `questions` (see CLAUDE.md).
                    if isinstance(related_diagnosis_ids, str):
                        try:
                            decoded = json.loads(related_diagnosis_ids)
                        except json.JSONDecodeError:
                            decoded = None
                        related_diagnosis_ids = decoded if isinstance(decoded, list) else [
                            d.strip() for d in related_diagnosis_ids.split(",") if d.strip()
                        ]
                    elif related_diagnosis_ids is not None and not isinstance(related_diagnosis_ids, list):
                        return {
                            "error": "related_diagnosis_ids must be a comma-separated string or an array of diagnosis IDs",
                            "guidance": "Pass related_diagnosis_ids as e.g. [\"d1\", \"d2\"] or \"d1,d2\"."
                        }

                    procedure_item: Dict[str, Any] = {
                        "item_quantity": item_quantity or 1,
                        "place_of_service": pos,
                    }
                    if code_id:
                        procedure_item["code_id"] = code_id
                    if item_charge is not None:
                        procedure_item["item_charge"] = item_charge
                    if modifier_1:
                        procedure_item["modifier_1"] = modifier_1
                    if modifier_2:
                        procedure_item["modifier_2"] = modifier_2
                    if modifier_3:
                        procedure_item["modifier_3"] = modifier_3
                    if modifier_4:
                        procedure_item["modifier_4"] = modifier_4
                    if claim_comments:
                        procedure_item["claim_comments"] = claim_comments
                    if related_diagnosis_ids:
                        procedure_item["related_diagnosis_ids"] = [
                            str(d).strip() for d in related_diagnosis_ids if str(d).strip()
                        ]
                    if action == "update":
                        procedure_item["consultation_cpt_map_id"] = consultation_cpt_map_id
                    if skip_invoice_check:
                        procedure_item["skip_invoice_check"] = True

                    # POST body is a batch envelope — {"procedures": [...]} — even for a
                    # single procedure. Confirmed against InvoicesAPIUtil.addOrUpdateCPTsForEncounter,
                    # which does inputStream.optJSONArray("procedures") and NPEs on a flat body.
                    # consultation_cpt_map_id presence/absence in each item (not a URL/action
                    # distinction) is what the real API uses to tell add from update.
                    response = await client.post(
                        f"/patients/{patient_id}/encounters/{encounter_id}/procedures",
                        data={"procedures": [procedure_item]}
                    )

                    if isinstance(response, dict) and response.get("error"):
                        error_msg = str(response["error"])
                        guidance = f"Failed to {action} the procedure. Verify code_id and consultation_cpt_map_id (if updating) are correct."
                        if "invoice" in error_msg.lower():
                            guidance = "An invoice already exists for this encounter, so procedures can't be modified without an explicit override. Retry with skip_invoice_check=True only if that's actually intended."
                        return {"error": error_msg, "guidance": guidance}

                    procedures = response.get("procedures") if isinstance(response, dict) else None
                    result = {"procedures": procedures or []}
                    result["guidance"] = f"Procedure {'added to' if action == 'add' else 'updated on'} the encounter. Use action='list' to see the full current set, or action='delete' with consultation_cpt_map_id to remove one."
                    return strip_empty_values(result)

                case "delete":
                    if not patient_id or not encounter_id or not consultation_cpt_map_id:
                        return {
                            "error": "patient_id, encounter_id, and consultation_cpt_map_id required for delete",
                            "guidance": "Use action='list' first to find the consultation_cpt_map_id of the procedure to remove."
                        }

                    # DELETE /patients/{pid}/encounters/{eid}/procedures/{cpt_map_id}
                    # (InvoicesAPI.removeProcedure) — confirmed against APIRequestByDelete.xml.
                    response = await client.delete(
                        f"/patients/{patient_id}/encounters/{encounter_id}/procedures/{consultation_cpt_map_id}"
                    )
                    if isinstance(response, dict) and response.get("error"):
                        return {
                            "error": response["error"],
                            "guidance": "Could not remove the procedure. Verify consultation_cpt_map_id is correct via action='list'."
                        }
                    return {"guidance": "Procedure removed from the encounter."}

        except Exception as e:
            logger.error(f"Error in manageEncounterProcedures: {e}")
            return {
                "error": str(e),
                "guidance": f"Failed to {action} encounter procedure. Verify patient_id, encounter_id, "
                            "and other required fields are correct."
            }
