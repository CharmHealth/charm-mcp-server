from fastmcp import FastMCP
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

scheduling_tools_mcp = FastMCP(name="CharmHealth Scheduling Tools MCP Server")

@scheduling_tools_mcp.tool
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
) -> Dict[str, Any]:
    """
    <usecase>
    Complete appointment lifecycle management - schedule new appointments, reschedule existing ones,
    cancel appointments, and list appointments with flexible filtering. Handles the full appointment workflow.
    </usecase>
    
    <instructions>
    Actions:
    - "schedule": Create new appointment (requires patient_id, provider_id, facility_id, appointment_date, appointment_time). Check the provider's availability with manageAppointments(action='list') and provider_id, and across all facilities for the provider before suggesting a time.
    - "reschedule": Change existing appointment time (requires appointment_id + new scheduling details)
    - "cancel": Cancel appointment (requires appointment_id + cancel_reason)
    - "list": Show appointments with filtering (requires start_date, end_date_range, facility_ids)
    
    Time format: Use 12-hour format like "09:30 AM" or "02:15 PM"
    For recurring: Set repetition to "Weekly" or "Daily" and provide frequency + end_date
    For double booking: Use provider_double_booking="allow" or resource_double_booking="allow" to override checks
    For cancellation: Use delete_type "Current" for single appointment or "Entire" for recurring series

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
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
                    
                    return response
                    
                case "reschedule":
                    required = [appointment_id, facility_id, patient_id, provider_id, appointment_date, appointment_time]
                    if not all(required):
                        return {
                            "error": "Missing required fields for rescheduling",
                            "guidance": "For rescheduling, provide: appointment_id, facility_id, patient_id, provider_id, appointment_date, appointment_time"
                        }
                    
                    # Build reschedule data
                    reschedule_data = {
                        "facility_id": facility_id,
                        "patient_id": patient_id,
                        "member_id": provider_id,
                        "mode": mode,
                        "repetition": repetition or "Single Date",
                        "start_date": appointment_date.isoformat(),
                        "start_time": appointment_time,
                        "duration_in_minutes": duration_minutes,
                        "appointment_status": status,
                        "visit_type_id": visit_type_id
                    }
                    
                    if reason:
                        reschedule_data["reason"] = reason
                    if message_to_patient:
                        reschedule_data["message_to_patient"] = message_to_patient
                    if resource_id:
                        reschedule_data["resource_id"] = resource_id
                    
                    data = {"data": reschedule_data}
                    
                    response = await client.post(f"/appointment/{appointment_id}/reschedule", data=data)
                    
                    if response.get("output_string"):
                        response["guidance"] = f"Appointment {appointment_id} rescheduled successfully. Patient will be notified of the new time."
                    elif response.get("error"):
                        error_msg = response["error"].lower()
                        if "double booking" in error_msg:
                            response["guidance"] = "Provider has a conflict at the new time. Try a different time slot."
                        else:
                            response["guidance"] = "Rescheduling failed. Verify the appointment exists and new details are valid."
                    
                    return response
                    
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
                    
                    return response
                    
                case "list":
                    required = [start_date, end_date_range, facility_ids]
                    if not all(required):
                        return {
                            "error": "Missing required fields for listing appointments",
                            "guidance": "For listing appointments, provide: start_date, end_date_range, and facility_ids (comma-separated)"
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
                    
                    if response.get("appointments"):
                        appt_count = len(response["appointments"])
                        response["guidance"] = f"Found {appt_count} appointments in the specified date range. Use action='reschedule' or action='cancel' to modify appointments."
                    
                    return response
                    
        except Exception as e:
            logger.error(f"Error in manageAppointments: {e}")
            return {
                "error": str(e),
                "guidance": f"Appointment {action} failed. Check your parameters and try again. Use getPracticeInfo() to verify provider and facility IDs."
            }
