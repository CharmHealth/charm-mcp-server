from fastmcp import FastMCP
from typing import Optional, List, Dict, Any
from datetime import datetime, date, timedelta
import sys
import os
from api_client import CharmHealthAPIClient
from utils import build_params_from_locals
import logging
from telemetry_config import telemetry
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from tool_metrics import with_tool_metrics
from telemetry_config import telemetry

logger = logging.getLogger(__name__)
practice_information_mcp = FastMCP(name="Practice Information")



@practice_information_mcp.tool
@with_tool_metrics()
async def list_facilities(
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    sort_order: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all facilities for the practice.
    """
    async with CharmHealthAPIClient() as client:
        try:
            params = {}
            if page:
                params["page"] = page
            if per_page:
                params["per_page"] = per_page
            if sort_order:
                params["sort_order"] = sort_order
            response = await client.get("/facilities", params=params)
            logger.info(f"Tool call completed for list_facilities, with message {response.get("message", "")} and code {response.get("code", "")}")
            return response
        except Exception as e:
            logger.error(f"Error in list_facilities: {e}")
            return {"error": str(e)}

@practice_information_mcp.tool
@with_tool_metrics()
async def list_members(
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    sort_order: Optional[str] = None,
    sort_column: Optional[str] = None,
    full_name: Optional[str] = None,
    full_name_startswith: Optional[str] = None,
    full_name_contains: Optional[str] = None,
    first_name: Optional[str] = None,
    first_name_startswith: Optional[str] = None,
    first_name_contains: Optional[str] = None,
    last_name: Optional[str] = None,
    last_name_startswith: Optional[str] = None,
    last_name_contains: Optional[str] = None,
    state: Optional[str] = None,
    state_startswith: Optional[str] = None,
    state_contains: Optional[str] = None,
    city: Optional[str] = None,
    city_startswith: Optional[str] = None,
    city_contains: Optional[str] = None,
    zip_code: Optional[str] = None,
    zip_code_startswith: Optional[str] = None,
    zip_code_contains: Optional[str] = None,
    mobile: Optional[str] = None,
    mobile_startswith: Optional[str] = None,
    mobile_contains: Optional[str] = None,
    home_phone: Optional[str] = None,
    home_phone_startswith: Optional[str] = None,
    home_phone_contains: Optional[str] = None,
    npi: Optional[str] = None,
    npi_startswith: Optional[str] = None,
    npi_contains: Optional[str] = None,
    specialization: Optional[str] = None,
    specialization_startswith: Optional[str] = None,
    specialization_contains: Optional[str] = None,
    facility_id: Optional[str] = None,
    license_state: Optional[str] = None,
    role_id: Optional[int] = None,
    privilege: Optional[str] = None,
    department_id: Optional[int] = None,
    email: Optional[str] = None,
    email_startswith: Optional[str] = None,
    email_contains: Optional[str] = None,
    filter_by: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List all members for the practice.
    
    Parameters:
    - page: Page number (optional)
    - per_page: Number of items per page (optional)
    - sort_order: Sort order - A (Ascending) or D (Descending) (optional)
    - sort_column: Sort column - created_date, first_name, last_name, specialization, full_name (optional)
    - full_name: Member full name with variants (full_name_startswith, full_name_contains)
    - first_name: Member first name with variants (first_name_startswith, first_name_contains)
    - last_name: Member last name with variants (last_name_startswith, last_name_contains)
    - state: State with variants (state_startswith, state_contains)
    - city: City with variants (city_startswith, city_contains)
    - zip_code: ZIP code with variants (zip_code_startswith, zip_code_contains)
    - mobile: Mobile number with variants (mobile_startswith, mobile_contains)
    - home_phone: Home phone with variants (home_phone_startswith, home_phone_contains)
    - npi: NPI with variants (npi_startswith, npi_contains)
    - specialization: Specialization with variants (specialization_startswith, specialization_contains)
    - facility_id: Facility IDs separated by commas
    - license_state: Filter by state license (US state name like Arkansas|Arizona|New York)
    - role_id: Role ID
    - privilege: Pass 'sign_encounter' to get only members with sign encounter privilege (i.e. providers)
    - department_id: Department ID
    - email: Email with variants (email_startswith, email_contains)
    - filter_by: Status filter - Status.Active / Status.Locked
    """
    async with CharmHealthAPIClient() as client:
        try:
            params = build_params_from_locals(locals())
            response = await client.get("/members", params=params)
            logger.info(f"Tool call completed for list_members, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in list_members: {e}")
            return {"error": str(e)}
        

@practice_information_mcp.tool
@with_tool_metrics()
async def list_available_vitals_for_practice(
) -> Dict[str, Any]:
    """
    List all available vitals for the practice.
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.get("/vitals/metrics")
            logger.info(f"Tool call completed for list_available_vitals_for_practice, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in list_available_vitals_for_practice: {e}")
            return {"error": str(e)}