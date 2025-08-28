from fastmcp import FastMCP
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

core_tools_mcp = FastMCP(name="CharmHealth Core Tools MCP Server")

@core_tools_mcp.tool
@with_tool_metrics()
async def findPatients(
    query: Optional[str] = None,
    search_type: Literal["name", "phone", "email", "record_id", "demographics", "advanced"] = "name",
    facility_id: Optional[str] = "ALL",
    limit: Optional[int] = 10,
    
    # Advanced search fields
    category_id: Optional[int] = None,
    gender: Optional[str] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    blood_group: Optional[str] = None,
    language: Optional[str] = None,
    marital_status: Optional[str] = None,
    
    # Location-based search
    state: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    postal_code: Optional[str] = None,
    
    # Time-based search  
    created_after: Optional[date] = None,
    created_before: Optional[date] = None,
    modified_after: Optional[date] = None,
    modified_before: Optional[date] = None,
    
    # Status and activity
    status: Optional[Literal["active", "inactive", "all"]] = "active",
    has_phr_account: Optional[bool] = None,
    
    # Sorting and pagination
    sort_by: Optional[Literal["name", "created_date", "modified_date"]] = "name",
    sort_order: Optional[Literal["asc", "desc"]] = "asc",
    page: Optional[int] = 1,
) -> Dict[str, Any]:
    """
    <usecase>
    Find patients quickly using natural search terms or specific criteria. Handles everything from 
    "find John Smith" to complex searches like "elderly diabetes patients in California". 
    Essential first step for any patient-related task.
    </usecase>
    
    <instructions>
    Quick searches: Use search_type="name" with query="John Smith" for basic name searches
    Phone lookups: Use search_type="phone" with query="555-1234" (handles any format)
    Medical record: Use search_type="record_id" with query="MR123456"
    
    Complex searches: Use search_type="advanced" with multiple criteria:
    - Age ranges: age_min=65, age_max=80 for elderly patients
    - Location: state="CA", city="Los Angeles" for geographic filtering  
    - Medical: blood_group="O+", language="Spanish" for clinical needs
    
    Always returns patient_id needed for other tools. Start here before any patient operations.

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Build parameters based on search type and criteria
            params = {
                "facility_id": facility_id, 
                "per_page": limit,
                "page": page
            }
            
            # Handle sorting
            if sort_by == "name":
                params["sort_column"] = "full_name"
            elif sort_by == "created_date":
                params["sort_column"] = "created_date"
            elif sort_by == "modified_date":
                params["sort_column"] = "modified_date"
            
            if sort_order == "asc":
                params["sort_order"] = "A"
            else:
                params["sort_order"] = "D"
            
            # Handle status filtering
            if status == "active":
                params["filter_by"] = "Status.Active"
            elif status == "inactive":
                params["filter_by"] = "Status.Locked"
            # "all" means no filter_by parameter
            
            match search_type:
                case "name":
                    if query:
                        if " " in query:
                            # Full name search
                            params["full_name_contains"] = query
                        else:
                            # Partial name - search both first and last
                            params["first_name_contains"] = query
                            
                case "phone":
                    if query:
                        clean_phone = query.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
                        params["mobile_contains"] = clean_phone
                        
                case "email":
                    if query:
                        params["email_contains"] = query
                        
                case "record_id":
                    if query:
                        params["record_id_contains"] = query
                        
                case "demographics":
                    # Use query for general demographic search if provided
                    if query:
                        params["full_name_contains"] = query
                        
                case "advanced":
                    # Multi-criteria search - query can be used for name if provided
                    if query:
                        params["full_name_contains"] = query
            
            # Apply advanced filters for demographics and advanced search types
            if search_type in ["demographics", "advanced"] or any([category_id, gender, age_min, age_max, blood_group, language, marital_status, state, city, country, postal_code, created_after, created_before, modified_after, modified_before, has_phr_account]):
                
                # Category and medical filters
                if category_id:
                    params["category_id"] = category_id
                if gender:
                    params["gender"] = gender
                if blood_group:
                    params["blood_group"] = blood_group
                if language:
                    params["language"] = language
                if marital_status:
                    params["marital_status"] = marital_status
                
                # Age range filtering
                if age_min:
                    params["age_greater_equals"] = age_min
                if age_max:
                    params["age_lesser_equals"] = age_max
                
                # Location filtering
                if state:
                    params["state"] = state
                if city:
                    params["city"] = city
                if country:
                    params["country"] = country
                if postal_code:
                    params["postal_code"] = postal_code
                
                # Date-based filtering
                if created_after:
                    params["created_date_start"] = created_after
                if created_before:
                    params["created_date_end"] = created_before
                
                # PHR account status
                if has_phr_account is not None:
                    params["is_phr_account_available"] = has_phr_account
            
            response = await client.get("/patients", params=params)
            
            # Enhanced response with intelligent guidance
            if response.get("patients"):
                patient_count = len(response["patients"])
                total_message = f"Found {patient_count} patient(s)"
                
                # Add search context to guidance
                search_context = []
                if search_type == "advanced" or any([age_min, age_max, blood_group, language, state, city]):
                    search_context.append("with applied filters")
                if query:
                    search_context.append(f"matching '{query}'")
                if facility_id != "ALL":
                    search_context.append(f"in facility {facility_id}")
                
                if search_context:
                    total_message += " " + " ".join(search_context)
                
                total_message += ". "
                
                # Provide contextual guidance based on results
                if patient_count == 0:
                    if search_type == "advanced":
                        message = total_message + "Try broadening your search criteria or removing some filters. Use search_type='name' for simple name searches."
                    else:
                        message = total_message + "Try a different search term, broader criteria, or search_type='advanced' for multi-criteria filtering."
                elif patient_count == 1:
                    patient = response["patients"][0]
                    patient_id = patient.get('id')
                    next_actions = []
                    
                    # Suggest immediate next actions based on common workflows
                    next_actions.append(f"reviewPatientHistory('{patient_id}') for complete clinical overview")
                    next_actions.append(f"managePatientAllergies(action='list', patient_id='{patient_id}') to check safety alerts")
                    next_actions.append(f"manageAppointments(action='list', patient_id='{patient_id}') for scheduling")
                    
                    message = total_message + f"Patient found: {patient.get('first_name', '')} {patient.get('last_name', '')}. " + \
                             f"Next steps: {' OR '.join(next_actions[:2])}."
                             
                elif patient_count >= limit:
                    message = total_message + f"Results limited to {limit}. Narrow search with more specific criteria, or use reviewPatientHistory() for each patient if reviewing multiple patients."
                else:
                    message = total_message + f"Multiple patients found. Select the correct patient_id, then use reviewPatientHistory() for clinical overview or managePatientAllergies() to check safety information."
                
                # Add filter suggestions based on current search
                suggestions = []
                if search_type != "advanced" and patient_count > 10:
                    suggestions.append("Consider using search_type='advanced' with demographic filters to narrow results")
                if not any([age_min, age_max]) and search_type in ["demographics", "advanced"]:
                    suggestions.append("Add age_min/age_max for age-based filtering")
                if not state and search_type in ["demographics", "advanced"]:
                    suggestions.append("Add state/city for location-based filtering")
                
                if suggestions:
                    message += " Suggestions: " + "; ".join(suggestions) + "."
                
                response["guidance"] = message
                response["search_summary"] = {
                    "search_type": search_type,
                    "total_results": patient_count,
                    "page": page,
                    "filters_applied": len([f for f in [category_id, gender, age_min, age_max, blood_group, language, state, city] if f is not None])
                }
            else:
                response["guidance"] = "No patients found. Check your search criteria and try again. Use search_type='name' for basic name searches or search_type='advanced' for complex filtering."
            
            logger.info(f"findPatients completed: {search_type} search with {patient_count if response.get('patients') else 0} results")
            return response
            
        except Exception as e:
            logger.error(f"Error in findPatients: {e}")
            return {
                "error": str(e),
                "guidance": "Search failed. Check your query format and parameters. For technical issues, verify API connectivity. Use simpler search criteria if advanced search fails."
            }

@core_tools_mcp.tool
@with_tool_metrics()
async def getPracticeInfo(
    info_type: Literal["facilities", "providers", "vitals", "overview"] = "overview"
) -> Dict[str, Any]:
    """
    <usecase>
    Get essential practice information needed for other operations - available facilities,
    providers, vital signs templates, etc. Use this to understand practice setup and get IDs for other tools.
    </usecase>
    
    <instructions>
    - "facilities": List all practice locations with IDs needed for scheduling
    - "providers": List all providers with IDs needed for appointments and encounters  
    - "vitals": Available vital sign templates for documentation
    - "overview": Summary of practice setup with key counts and recent activity

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            result = {"practice_info_type": info_type}
            
            # Use match for single-purpose info types, handle overview separately
            match info_type:
                case "facilities":
                    facilities_response = await client.get("/facilities")
                    result["facilities"] = facilities_response.get("facilities", [])
                    result["guidance"] = "Use facility IDs from this list when scheduling appointments or creating encounters. Each patient must be assigned to at least one facility."
                case "providers":
                    # Get providers (members with sign encounter privilege)
                    providers_response = await client.get("/members", params={"privilege": "sign_encounter"})
                    result["providers"] = providers_response.get("members", [])
                    result["guidance"] = "Use provider IDs (member_id) from this list when scheduling appointments or documenting encounters. Only providers with 'sign_encounter' privilege can sign clinical documentation."
                case "vitals":
                    vitals_response = await client.get("/vitals/metrics")
                    result["available_vitals"] = vitals_response.get("vitals", [])
                    result["guidance"] = "Use these vital sign names when documenting patient vitals in encounters. Common vitals include Weight, Height, Blood Pressure, Pulse Rate, Temperature."
                case "overview":
                    # Get all data for overview
                    facilities_response = await client.get("/facilities")
                    result["facilities"] = facilities_response.get("facilities", [])
                    result["facility_count"] = len(result["facilities"])
                    
                    providers_response = await client.get("/members", params={"privilege": "sign_encounter"})
                    result["providers"] = providers_response.get("members", [])
                    result["provider_count"] = len(result["providers"])
                    
                    vitals_response = await client.get("/vitals/metrics")
                    result["available_vitals"] = vitals_response.get("vitals", [])
                    result["vital_types_count"] = len(result["available_vitals"])
                    result["guidance"] = "Practice overview complete. Use specific info_type values to get detailed lists with IDs needed for patient operations."
            
            logger.info(f"getPracticeInfo completed for {info_type}")
            return result
            
        except Exception as e:
            logger.error(f"Error in getPracticeInfo: {e}")
            return {
                "error": str(e),
                "guidance": "Failed to retrieve practice information. Check API connectivity and permissions."
            } 
