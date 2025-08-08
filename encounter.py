from fastmcp import FastMCP
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta, time
import sys
import os
from api_client import CharmHealthAPIClient
from utils import build_params_from_locals
import logging
from tool_metrics import with_tool_metrics
from telemetry_config import telemetry
import contextvars

telemetry.initialize()

logger = logging.getLogger(__name__)

encounter_mcp = FastMCP(name="Encounter")


@encounter_mcp.tool
@with_tool_metrics()
async def list_encounters(
    member_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    filter_by: Optional[str] = None, # Status.Signed, Status.Unsigned, Status.All
    facility_id: Optional[str] = None,
    approved_time_greater_than: Optional[int] = None,
    approved_time_less_than: Optional[int] = None,
    encounter_time_greater_equals: Optional[int] = None,
    encounter_time_less_equals: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    sort_order: Optional[str] = None, # A, D
) -> Dict[str, Any]:
    """
    Get encounters for a patient from CharmHealth.
    """
    async with CharmHealthAPIClient() as client:
        try:
            params = build_params_from_locals(locals())
            response = await client.get("/encounters", params=params)
            logger.info(f"Tool call completed for list_encounters, with message {response.get("message", "")} and code {response.get("code", "")}")
            return response
        except Exception as e:
            logger.error(f"Error in list_encounters: {e}")
            return {"error": str(e)}

@encounter_mcp.tool
@with_tool_metrics()
async def get_encounter_details(
    encounter_id: str,
    is_soap: Optional[bool] = True,
) -> Dict[str, Any]:
    """
    Get an encounter by ID from CharmHealth.
    """
    async with CharmHealthAPIClient() as client:
        try:
            if is_soap:
                response = await client.get(f"/soap/encounters/{encounter_id}")
                logger.info(f"Tool call completed for get_encounter_details, with message {response.get("message", "")} and code {response.get("code", "")}")
                return response
            else:
                response = await client.get(f"/encounters/{encounter_id}")
                logger.info(f"Tool call completed for get_encounter_details, with message {response.get("message", "")} and code {response.get("code", "")}")
                return response
        except Exception as e:
            logger.error(f"Error in get_encounter_details: {e}")
            return {"error": str(e)}


@with_tool_metrics()
@encounter_mcp.tool
async def create_encounter(
    appointment_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    member_id: Optional[str] = None,
    date: Optional[date] = None,
    chart_type: str = "SOAP",
    encounter_mode: str = "In Person",  # In Person, Phone Call, Video Consult
    time: Optional[time] = None,        # 12 hour format e.g. "02:30 PM"
    visit_type_id: Optional[str] = None,
    facility_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an encounter in CharmHealth.
    If appointment_id is provided, creates an encounter from the appointment.
    Otherwise, creates an encounter for a patient without a prior appointment.
    """
    async with CharmHealthAPIClient() as client:
        try:
            if appointment_id:
                # Create from appointment
                return await client.post(
                    f"/appointments/{appointment_id}/encounter",
                    data={"chart_type": chart_type}
                )
            else:
                # Create for patient without prior appointment
                if not (patient_id and member_id and date):
                    return {"error": "patient_id, member_id, and date are required if appointment_id is not provided."}
                params = build_params_from_locals(locals())
                params["provider_id"] = member_id
                params.pop("member_id")
                # params.pop("appointment_id")
                params.pop("patient_id")
                response = await client.post(f"/patients/{patient_id}/encounter", data=params)
                logger.info(f"Tool call completed for create_encounter, with message {response.get("message", "")} and code {response.get("code", "")}")
                return response
        except Exception as e:
            logger.error(f"Error in create_encounter: {e}")
            return {"error": str(e)}


@encounter_mcp.tool
@with_tool_metrics()
async def save_encounter(
    encounter_id: str,
    patient_id: Optional[str] = None,
    chief_complaints: Optional[str] = None,
    symptoms: Optional[str] = None,
    physical_examination: Optional[str] = None,
    treatment_notes: Optional[str] = None,
    self_notes: Optional[str] = None,
    patient_notes: Optional[str] = None,
    lifestyle: Optional[str] = None,
    diets: Optional[str] = None,
    assessment_notes: Optional[str] = None,
    psychotherapy_notes: Optional[str] = None,
    followup_notes: Optional[str] = None,
    present_illness_history: Optional[str] = None,
    family_social_history: Optional[str] = None,
    review_of_systems: Optional[str] = None,
    past_medical_history: Optional[str] = None,
    condition_related_to: Optional[str] = None,
    accident_place: Optional[str] = None,
    is_html: Optional[str] = False,
    # SOAP encounter specific parameters
    use_soap_api: Optional[bool] = False,
    entries: Optional[Dict[str, Any]] = None,
):
    """
    Save an encounter in CharmHealth using either the regular encounter API or SOAP encounter API.
    
    Args:
        use_soap_api: If True, uses the SOAP encounter API endpoint
        entries: For SOAP API - Dictionary containing template entries with entry_id and answer
                Example: {"entry_id": 123, "answer": "Patient response"}
    """
    async with CharmHealthAPIClient() as client:
        try:
            if use_soap_api:
                # Use SOAP encounter API
                soap_data = {}
                
                # Add chief_complaints if provided
                if chief_complaints:
                    soap_data["chief_complaints"] = chief_complaints
                    
                # Add entries if provided
                if entries:
                    soap_data["entries"] = entries
                
                # Prepare the data structure for SOAP API
                request_data = {"data": soap_data}
                
                return await client.post(f"/soap/encounters/{encounter_id}", data=request_data)
            else:
                # Use original encounter API
                params = build_params_from_locals(locals(), exclude=["use_soap_api", "entries"])
                if patient_id:
                    response = await client.post(f"/patients/{patient_id}/encounters/{encounter_id}/save", data=params)
                    logger.info(f"Tool call completed for save_encounter, with message {response.get("message", "")} and code {response.get("code", "")}")
                    return response
                else:
                    return {"error": "patient id is required to save a non-SOAP encounter for a patient."}
        except Exception as e:
            logger.error(f"Error in save_encounter: {e}")
            return {"error": str(e)}


