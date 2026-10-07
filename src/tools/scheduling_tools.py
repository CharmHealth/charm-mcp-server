from fastmcp import FastMCP, Context
from common.auth import resolve_auth
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals, strip_empty_values
from common.filtering import filter_items
from common.app_views import app_result
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

scheduling_tools_mcp = FastMCP(name="CharmHealth Scheduling Tools MCP Server")

async def _known_facilities(client) -> List[Dict[str, Any]]:
    """The practice's facilities, or an empty list if they can't be fetched.

    Fails open on purpose: this only ever adds a note to a guidance string, so a
    lookup failure must never change the answer.
    """
    try:
        response = await client.get("/facilities")
    except Exception:
        return []
    if not isinstance(response, dict) or "error" in response:
        return []
    return [f for f in (response.get("facilities") or []) if isinstance(f, dict)]


def _empty_result_guidance(facilities: List[Dict[str, Any]], facility_ids: Optional[str]) -> str:
    """Guidance for an empty appointment list, flagging an unknown facility id.

    Every value is read from the request and the live response — nothing about
    this practice is hard-coded.
    """
    base = "No appointments found in this date range."
    supplied = [part.strip() for part in str(facility_ids or "").split(",") if part.strip()]
    if not facilities or not supplied:
        return base

    known = {str(f.get("facility_id")) for f in facilities if f.get("facility_id")}
    if not known or any(value in known for value in supplied):
        return base

    listed = ", ".join(
        f"{f.get('facility_id')} ({f.get('facility_name')})" if f.get("facility_name")
        else str(f.get("facility_id"))
        for f in facilities if f.get("facility_id")
    )
    return (
        f"{base} WARNING: facility_ids={','.join(supplied)} does not match any facility "
        f"in this practice, so this empty result is probably wrong rather than an empty "
        f"schedule. Valid facility_ids: {listed}. Retry with one of those."
    )


@scheduling_tools_mcp.tool(app=True)
@with_tool_metrics()
async def manageAppointments(
    action: Literal["schedule", "reschedule", "cancel", "list"],
    # Common fields
    patient_id: Optional[str] = None,
    appointment_id: Optional[str] = None,
    
    # Scheduling fields
    provider_id: Optional[str] = None,
    facility_id: Optional[str] = None,
    appointment_date: Optional[date] = None,
    appointment_time: Optional[str] = None,  # Format: "09:30 AM"
    duration_minutes: Optional[int] = 30,
    mode: Optional[Literal["In Person", "Phone call", "Video Consult"]] = "In Person",
    reason: Optional[str] = None,
    status: Optional[Literal["Confirmed", "Pending", "Tentative", "Cancelled"]] = "Confirmed",
    visit_type_id: Optional[int] = None,
    
    # Recurring appointment fields
    repetition: Optional[str] = "Single Date",
    frequency: Optional[str] = None,  # daily|weekly
    end_date: Optional[date] = None,
    weekly_days: Optional[List[Dict[str, str]]] = None,
    
    # Advanced fields
    message_to_patient: Optional[str] = None,
    questionnaire: Optional[List[Dict[str, int]]] = None,
    consent_forms: Optional[List[Dict[str, int]]] = None,
    resource_id: Optional[int] = None,
    provider_double_booking: Optional[str] = None,  # "allow" to override double booking check
    resource_double_booking: Optional[str] = None,  # "allow" to override resource double booking check
    receipt_id: Optional[int] = None,
    
    # Cancellation fields
    cancel_reason: Optional[str] = None,
    delete_type: Optional[str] = None,  # Current|Entire
    
    # Listing fields
    start_date: Optional[date] = None,
    end_date_range: Optional[date] = None,
    facility_ids: Optional[str] = None,  # Comma-separated
    member_ids: Optional[str] = None,   # Comma-separated
    status_ids: Optional[str] = None,   # Comma-separated

    # Additional list filters (applied client-side after fetching)
    status_filter: Optional[str] = None,
    provider_filter: Optional[str] = None,  # provider_id or provider_name (substring match)
    mode_filter: Optional[str] = None,
    limit: Optional[int] = None,

    response_format: Optional[Literal["concise", "detailed"]] = None,  # reserved for cortex; no behavior change yet (J13/CH-695)

    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage appointments.
    
    <usecase>
    Complete appointment lifecycle management - schedule new appointments, reschedule existing ones,
    cancel appointments, and list appointments with flexible filtering. Handles the full appointment workflow.
    </usecase>
    
    <instructions>
    Actions:
    - "schedule": Create new appointment (requires patient_id, provider_id, facility_id, appointment_date, appointment_time). Check the provider's availability with manageAppointments(action='list') and provider_id, and across all facilities for the provider before suggesting a time.
    - "reschedule": Change existing appointment time (requires appointment_id + new scheduling details)
    - "cancel": Cancel appointment (requires appointment_id + cancel_reason)
    - "list": Show appointments with filtering (requires start_date, end_date_range, facility_ids; optionally filter by status/provider/mode)

    facility_ids is a comma-separated list of REAL facility IDs, e.g.
    facility_ids="1995529000000021081" or facility_ids="1995529000000021081,1995529000000021082".
    There is no "all" or wildcard value — the API rejects anything that is not an
    ID with: {"code":2,"error_input":"facility_ids","message":"Invalid value passed
    for facility_ids"}. If you do not have the IDs, call
    getPracticeInfo(info_type="facilities") first and use the facility_id values it
    returns.
    
    Time format: Use 12-hour format like "09:30 AM" or "02:15 PM"
    For recurring: Set repetition to "Weekly" or "Daily" and provide frequency + end_date
    For double booking: Use provider_double_booking="allow" or resource_double_booking="allow" to override checks
    For cancellation: Use delete_type "Current" for single appointment or "Entire" for recurring series

    List filters (applied after fetching all appointments in the date range):
    - status_filter: e.g., status_filter="Confirmed"
    - provider_filter: provider_id or provider_name substring (e.g., provider_filter="12345" or provider_filter="Smith")
    - mode_filter: e.g., mode_filter="Video Consult"
    - limit: e.g., limit=25

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    auth = resolve_auth("manageAppointments")
    
    async with CharmHealthAPIClient(**auth.client_kwargs()) as client:
        try:
            match action:
                case "schedule":
                    required = [patient_id, provider_id, facility_id, appointment_date, appointment_time]
                    if not all(required):
                        return {
                            "error": "Missing required fields for scheduling",
                            "guidance": "For scheduling, provide: patient_id, provider_id, facility_id, appointment_date, and appointment_time"
                        }
                    
                    # Prepare appointment data
                    appointment_data = {
                        "patient_id": int(patient_id),
                        "facility_id": int(facility_id),
                        "member_id": int(provider_id),
                        "mode": mode,
                        "repetition": repetition,
                        "appointment_status": status,
                        "start_date": appointment_date.isoformat(),
                        "start_time": appointment_time,
                        "duration_in_minutes": duration_minutes
                    }
                    
                    # Add optional fields
                    if reason:
                        appointment_data["reason"] = reason
                    if visit_type_id:
                        appointment_data["visit_type_id"] = visit_type_id
                    if end_date:
                        appointment_data["end_date"] = end_date.isoformat()
                    if frequency:
                        appointment_data["frequency"] = frequency
                    if weekly_days:
                        appointment_data["weekly_days"] = weekly_days
                    if message_to_patient:
                        appointment_data["message_to_patient"] = message_to_patient
                    if questionnaire:
                        appointment_data["questionnaire"] = questionnaire
                    if consent_forms:
                        appointment_data["consent_forms"] = consent_forms
                    if resource_id:
                        appointment_data["resource_id"] = resource_id
                    if provider_double_booking:
                        appointment_data["provider_double_booking"] = provider_double_booking
                    if resource_double_booking:
                        appointment_data["resource_double_booking"] = resource_double_booking
                    if receipt_id:
                        appointment_data["receipt_id"] = receipt_id
                    
                    # Send data directly as the appointment object (not wrapped in "data")
                    response = await client.post("/appointments", data=appointment_data)
                    
                    if response.get("appointment") or response.get("data"):
                        appt_id = response.get("appointment", {}).get("id") or response.get("data", {}).get("id")
                        response["guidance"] = f"Appointment scheduled successfully (ID: {appt_id}). Use manageEncounter()() after the visit to record clinical findings."
                    elif response.get("error"):
                        error_msg = response["error"].lower()
                        if "double booking" in error_msg:
                            response["guidance"] = "Provider has a conflict at this time. Try a different time slot or check provider availability."
                        elif "invalid" in error_msg:
                            response["guidance"] = "Check that provider_id and facility_id are valid. Use getPracticeInfo() to see available providers and facilities."
                        else:
                            response["guidance"] = "Scheduling failed. Verify all IDs are correct and the time slot is in the future during business hours."
                    
                    return strip_empty_values(response)
                    
                case "reschedule":
                    # Auto-fill missing fields from the existing appointment
                    if appointment_id and (not patient_id or not facility_id or not provider_id or not visit_type_id):
                        try:
                            appt_response = await client.get(f"/appointment/{appointment_id}")
                            appt = appt_response.get("output_string") or appt_response.get("appointment") or {}
                            if appt:
                                patient_id = patient_id or str(appt.get("practice_patient_id", ""))
                                facility_id = facility_id or str(appt.get("facility_id", ""))
                                provider_id = provider_id or str(appt.get("member_id", ""))
                                if not visit_type_id and appt.get("visit_type_id"):
                                    visit_type_id = int(appt["visit_type_id"])
                                if mode == "In Person" and appt.get("appointment_type"):
                                    mode = appt["appointment_type"]
                        except Exception as e:
                            logger.warning(f"Could not auto-fill reschedule fields from appointment {appointment_id}: {e}")

                    required = [appointment_id, facility_id, patient_id, provider_id, appointment_date, appointment_time]
                    if not all(required):
                        return {
                            "error": "Missing required fields for rescheduling",
                            "guidance": "For rescheduling, provide: appointment_id, facility_id, patient_id, provider_id, appointment_date, appointment_time"
                        }

                    # Build reschedule data (IDs must be integers, matching CharmHealth API Long type)
                    reschedule_data = {
                        "facility_id": int(facility_id),
                        "patient_id": int(patient_id),
                        "member_id": int(provider_id),
                        "mode": mode,
                        "repetition": repetition or "Single Date",
                        "start_date": appointment_date.isoformat(),
                        "start_time": appointment_time,
                        "duration_in_minutes": duration_minutes,
                        "appointment_status": status,
                    }
                    if visit_type_id:
                        reschedule_data["visit_type_id"] = int(visit_type_id)
                    
                    if reason:
                        reschedule_data["reason"] = reason
                    if message_to_patient:
                        reschedule_data["message_to_patient"] = message_to_patient
                    if resource_id:
                        reschedule_data["resource_id"] = resource_id
                    if questionnaire:
                        reschedule_data["questionnaire"] = questionnaire
                    if consent_forms:
                        reschedule_data["consent_forms"] = consent_forms

                    response = await client.post(f"/appointment/{appointment_id}/reschedule", data=reschedule_data)
                    
                    if response.get("output_string"):
                        response["guidance"] = f"Appointment {appointment_id} rescheduled successfully. Patient will be notified of the new time."
                    elif response.get("error"):
                        error_msg = response["error"].lower()
                        if "double booking" in error_msg:
                            response["guidance"] = "Provider has a conflict at the new time. Try a different time slot."
                        else:
                            response["guidance"] = "Rescheduling failed. Verify the appointment exists and new details are valid."
                    
                    return strip_empty_values(response)
                    
                case "cancel":
                    if not appointment_id or not cancel_reason:
                        return {
                            "error": "appointment_id and cancel_reason required for cancellation",
                            "guidance": "Provide the appointment_id to cancel and a reason for the cancellation."
                        }
                    
                    cancel_data = {"reason": cancel_reason}
                    if delete_type:
                        cancel_data["delete_type"] = delete_type
                    
                    response = await client.post(f"/appointments/{appointment_id}/cancel", data=cancel_data)
                    
                    if response.get("code") == "0":
                        response["guidance"] = f"Appointment {appointment_id} cancelled successfully. Patient will be notified of the cancellation."
                    else:
                        response["guidance"] = "Cancellation failed. Verify the appointment_id exists and is not already cancelled."
                    
                    return strip_empty_values(response)
                    
                case "list":
                    if facility_ids and facility_ids.strip().lower() in ("all", "*", "any"):
                        # A model with no practice context guesses a wildcard here.
                        # The API answers with an opaque 400, so say what is wrong
                        # and how to get the real values.
                        return {
                            "error": f"facility_ids={facility_ids!r} is not valid — there is no wildcard value",
                            "guidance": "facility_ids must be a comma-separated list of real facility IDs. Call getPracticeInfo(info_type='facilities') and pass the facility_id values it returns.",
                        }
                    required = [start_date, end_date_range, facility_ids]
                    if not all(required):
                        return {
                            "error": "Missing required fields for listing appointments",
                            "guidance": "For listing appointments, provide: start_date, end_date_range, and facility_ids. facility_ids must be a comma-separated list of real facility IDs — there is no 'all' value. Call getPracticeInfo(info_type='facilities') to get them."
                        }
                    
                    # Build query parameters
                    params = {
                        "start_date": start_date.strftime("%Y-%m-%d"),
                        "end_date": end_date_range.strftime("%Y-%m-%d"),
                        "facility_ids": facility_ids
                    }
                    
                    if patient_id:
                        params["patient_id"] = patient_id
                    if member_ids:
                        params["member_ids"] = member_ids
                    if status_ids:
                        params["status_ids"] = status_ids
                    
                    response = await client.get("/appointments", params=params)

                    appts = response.get("appointments") or []
                    total_count = len(appts)

                    wrappers = []
                    for a in appts:
                        status_val = (a or {}).get("appointment_status") or (a or {}).get("status")
                        mode_val = (a or {}).get("mode")
                        provider_id_val = (a or {}).get("member_id") or (a or {}).get("provider_id")
                        provider_name_val = (a or {}).get("member_name") or (a or {}).get("physician_name")
                        provider_search = f"{provider_id_val or ''} {provider_name_val or ''}".strip()
                        # Canonical display-name field (additive, J13/CH-695):
                        # previously provider_name_val was only computed for
                        # this internal search string, then discarded — the
                        # returned appointment item itself never carried it.
                        # Attach it to the raw item (a is what "_orig" below
                        # points at and actually gets returned).
                        if isinstance(a, dict) and provider_name_val:
                            a.setdefault("provider_name", provider_name_val)
                        wrappers.append({
                            **(a or {}),
                            "_orig": a,
                            "status": status_val,
                            "mode": mode_val,
                            "provider_search": provider_search,
                        })

                    filters: Dict[str, Any] = {}
                    if status_filter:
                        filters["status"] = status_filter
                    if mode_filter:
                        filters["mode"] = mode_filter
                    if provider_filter:
                        filters["provider_search"] = {"op": "contains", "value": provider_filter}

                    filtered = filter_items(wrappers, filters=filters or None, limit=limit)
                    response["appointments"] = [w.get("_orig", w) for w in filtered["items"]]
                    response["total_count"] = total_count
                    response["filtered_count"] = filtered["filtered_count"]

                    if response.get("appointments"):
                        response["guidance"] = (
                            f"Found {total_count} appointments in the specified date range; {filtered['filtered_count']} match the provided filters."
                            " Use action='reschedule' or action='cancel' to modify appointments."
                        )
                    else:
                        # A facility id this practice does not have is *accepted*
                        # by the API — it answers 200 with an empty list rather
                        # than an error — so a quiet day and a wrong facility are
                        # indistinguishable to the caller. Observed live: a
                        # caller passed facility_ids="1", got an empty result,
                        # and reported the schedule as clear.
                        #
                        # Say so in the guidance rather than raising: an empty
                        # schedule is a legitimate answer, and turning it into an
                        # error would break the common case to catch the rare one.
                        response["guidance"] = _empty_result_guidance(
                            await _known_facilities(client), facility_ids
                        )

                    return app_result(strip_empty_values(response), "appointment_list")
                    
        except Exception as e:
            logger.error(f"Error in manageAppointments: {e}")
            return {
                "error": str(e),
                "guidance": f"Appointment {action} failed. Check your parameters and try again. Use getPracticeInfo() to verify provider and facility IDs."
            }
