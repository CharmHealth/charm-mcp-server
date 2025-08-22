from fastmcp import FastMCP
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals
import logging
from telemetry import telemetry, with_tool_metrics

telemetry.initialize()
logger = logging.getLogger(__name__)

charm_mcp = FastMCP(name="CharmHealth MCP Server")

@charm_mcp.tool
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
                    next_actions.append(f"managePatientAppointments(action='list', patient_id='{patient_id}') for scheduling")
                    
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

@charm_mcp.tool
@with_tool_metrics()
async def managePatient(
    action: Literal["create", "update", "activate", "deactivate"],
    patient_id: Optional[str] = None,
    
    # Core patient info (required for create/update)
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    gender: Optional[Literal["male", "female", "unknown", "other"]] = None,
    date_of_birth: Optional[date] = None,
    age: Optional[str] = None,  # Alternative to date_of_birth
    
    # Extended name fields
    middle_name: Optional[str] = None,
    nick_name: Optional[str] = None,
    suffix: Optional[str] = None,
    maiden_name: Optional[str] = None,
    gender_identity: Optional[str] = None,
    
    # Contact info
    phone: Optional[str] = None,  # Mobile phone
    home_phone: Optional[str] = None,
    work_phone: Optional[str] = None,
    work_phone_extn: Optional[str] = None,
    primary_phone: Optional[Literal["Home Phone", "Mobile Phone", "Work Phone"]] = None,
    email: Optional[str] = None,
    
    # Address (comprehensive)
    address_line1: Optional[str] = None,
    address_line2: Optional[str] = None,
    area: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    county_code: Optional[str] = None,
    zip_code: Optional[str] = None,
    post_box: Optional[int] = None,
    district: Optional[str] = None,
    country: Optional[str] = "US",
    
    # Administrative
    facility_ids: Optional[str] = None, # Pass as comma separated list of facility ids in string format
    record_id: Optional[str] = None,
    categories: Optional[List[Dict[str, Any]]] = None,  # [{"category_id": category_id}]
    
    # Medical info
    blood_group: Optional[Literal["unknown", "B+", "B-", "O+", "O-", "A+", "A-", "A1+", "A1-", "A2+", "A2-", "AB+", "AB-", "A1B+", "A1B-", "A2B+", "A2B-"]] = None,
    language: Optional[str] = None,
    
    # Social history and demographics
    race: Optional[str] = None,
    ethnicity: Optional[str] = None,
    smoking_status: Optional[Literal["Current every day smoker", "Current some day smoker", "Former Smoker", "Never Smoker", "Smoker current status unknown", "Unknown if ever smoked", "Heavy tobacco smoker", "Light tobacco smoker"]] = None,
    marital_status: Optional[Literal["Single", "Married", "Other"]] = None,
    employment_status: Optional[Literal["Employed", "Full-Time Student", "Part-Time Student", "Unemployed", "Retired"]] = None,
    sexual_orientation: Optional[str] = None,
    
    # Family information
    mother_first_name: Optional[str] = None,
    mother_last_name: Optional[str] = None,
    is_multiple_birth: Optional[bool] = None,
    birth_order: Optional[int] = None,
    
    # Emergency contact
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
    emergency_extn: Optional[str] = None,
    
    # Communication preferences
    preferred_communication: Optional[Literal["ChARM PHR", "Email", "Phone", "Fax", "Mail"]] = None,
    email_notification: Optional[bool] = None,
    text_notification: Optional[bool] = None,
    voice_notification: Optional[bool] = None,
    
    # Custom fields
    introduction: Optional[str] = None,  # Patient introduction/notes
    custom_field_1: Optional[str] = None,
    custom_field_2: Optional[str] = None,
    custom_field_3: Optional[str] = None,
    custom_field_4: Optional[str] = None,
    custom_field_5: Optional[str] = None,
    
    # Payment and source information
    source_name: Optional[str] = None,
    source_value: Optional[str] = None,
    payment_source: Optional[str] = None,
    payment_start_date: Optional[date] = None,
    payment_end_date: Optional[date] = None,
    
    # Representative information
    rep_first_name: Optional[str] = None,
    rep_last_name: Optional[str] = None,
    
    # End of life information
    deceased: Optional[bool] = None,
    dod: Optional[date] = None,  # Date of death
    cause_of_death: Optional[str] = None,
    
    # Complex relationships (simplified structure for AI use)
    caregivers: Optional[List[Dict[str, Any]]] = None,
    guarantor: Optional[List[Dict[str, Any]]] = None,
    linked_patient_id: Optional[int] = None,
    id_qualifiers: Optional[List[Dict[str, Any]]] = None,
    
    # Control flags
    send_phr_invite: Optional[bool] = False,
    duplicate_check: Optional[bool] = True,
    update_specific_details: Optional[bool] = True,
) -> Dict[str, Any]:
    """
    <usecase>
    Complete patient management with comprehensive demographic, social, and administrative data.
    Handles patient creation, updates, status changes, and complex relationships. Supports all 
    CharmHealth patient data fields for complete EHR functionality.
    </usecase>
    
    <instructions>
    Actions:
    - "create": Add new patient (requires first_name, last_name, gender, date_of_birth OR age, facility_ids)
    - "update": Modify existing patient (requires patient_id + fields to change).
    - "activate": Reactivate deactivated patient (requires patient_id only)
    - "deactivate": Deactivate patient (requires patient_id only)
    
    Update Modes:
    - update_specific_details=True: Only updates the fields you provide, preserves all other existing data (RECOMMENDED, Default)
    - update_specific_details=False: Complete record update - must provide all fields or existing data will be lost
    
    Demographics: Supports comprehensive patient information including social history, family data
    Addresses: If any address field provided, country is required (defaults to US)
    Facilities: Pass as list of facility IDs like "facility_123,facility_456".
    Categories: Pass as list like [{"category_id": "category_123"}]
    
    Complex Relationships:
    - caregivers: [{"first_name": str, "last_name": str, "relationship": str, "contact": {...}, "address": {...}}]
    - guarantor: [{"first_name": str, "last_name": str, "relationship": str, "contact": {...}, "address": {...}}]
    - id_qualifiers: [{"id_qualifier": 1-8 or 99, "id_of_patient": "ID_value"}]

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            match action:
                case "create":
                    # Validate required fields
                    required = [first_name, last_name, gender, facility_ids]
                    if not all(required):
                        return {
                            "error": "Missing required fields for patient creation",
                            "guidance": "For creating patients, provide: first_name, last_name, gender, facility_ids, and either date_of_birth or age. Use getPracticeInfo() to get available facility IDs."
                        }
                    
                    # Either date_of_birth or age is required
                    if not date_of_birth and not age:
                        return {
                            "error": "Either date_of_birth or age is required",
                            "guidance": "Provide either the patient's date_of_birth (YYYY-MM-DD format) or their age in years."
                        }
                    
                    # Build comprehensive patient data
                    patient_data = {
                        "first_name": first_name,
                        "last_name": last_name,
                        "gender": gender,
                        "facilities": [{"facility_id": int(fid)} for fid in facility_ids.split(",")]
                    }
                    
                    # Add date of birth or age
                    if date_of_birth:
                        patient_data["dob"] = date_of_birth.isoformat()
                    if age:
                        patient_data["age"] = int(age)
                    
                    # Extended name fields
                    if middle_name:
                        patient_data["middle_name"] = middle_name
                    if nick_name:
                        patient_data["nick_name"] = nick_name
                    if suffix:
                        patient_data["suffix"] = suffix
                    if maiden_name:
                        patient_data["maiden_name"] = maiden_name
                    if gender_identity:
                        patient_data["gender_identity"] = gender_identity
                    if record_id:
                        patient_data["record_id"] = record_id
                    
                    # End of life information
                    if deceased is not None:
                        patient_data["deceased"] = deceased
                    if dod:
                        patient_data["dod"] = dod.isoformat()
                    if cause_of_death:
                        patient_data["cause_of_death"] = cause_of_death
                    if linked_patient_id:
                        patient_data["linked_patient_id"] = linked_patient_id
                    
                    # ID qualifiers array
                    if id_qualifiers:
                        patient_data["id_qualifiers"] = id_qualifiers
                    
                    # Address object (if any address field provided, country is required per API)
                    address_fields = [address_line1, address_line2, area, city, state, county_code, zip_code, post_box, district]
                    if any(address_fields):
                        patient_data["address"] = {
                            "country": country  # Required field per API
                        }
                        if address_line1:
                            patient_data["address"]["address_line1"] = address_line1
                        if address_line2:
                            patient_data["address"]["address_line2"] = address_line2
                        if area:
                            patient_data["address"]["area"] = area
                        if city:
                            patient_data["address"]["city"] = city
                        if state:
                            patient_data["address"]["state"] = state
                        if county_code:
                            patient_data["address"]["county_code"] = county_code
                        if zip_code:
                            patient_data["address"]["zip_code"] = zip_code
                        if post_box:
                            patient_data["address"]["post_box"] = post_box
                        if district:
                            patient_data["address"]["district"] = district
                    
                    # Contact information
                    if phone:
                        patient_data["mobile"] = phone
                    if home_phone:
                        patient_data["home_phone"] = home_phone
                    if work_phone:
                        patient_data["work_phone"] = work_phone
                    if work_phone_extn:
                        patient_data["work_phone_extn"] = work_phone_extn
                    if email:
                        patient_data["email"] = email
                    if primary_phone:
                        patient_data["primary_phone"] = primary_phone
                    
                    # Emergency contact
                    if emergency_contact_name:
                        patient_data["emergency_contact_name"] = emergency_contact_name
                    if emergency_contact_phone:
                        patient_data["emergency_contact_number"] = emergency_contact_phone
                    if emergency_extn:
                        patient_data["emergency_extn"] = emergency_extn
                    
                    # Caregivers array
                    if caregivers:
                        patient_data["caregivers"] = caregivers
                    
                    # Guarantor array
                    if guarantor:
                        patient_data["guarantor"] = guarantor
                    
                    # Communication preferences
                    if preferred_communication:
                        patient_data["preferred_communication"] = preferred_communication
                    if email_notification is not None:
                        patient_data["email_notification"] = email_notification
                    if text_notification is not None:
                        patient_data["text_notification"] = text_notification
                    if voice_notification is not None:
                        patient_data["voice_notification"] = voice_notification
                    
                    # Medical and demographic information
                    if blood_group:
                        patient_data["blood_group"] = blood_group
                    if language:
                        patient_data["language"] = language
                    if race:
                        patient_data["race"] = race
                    if ethnicity:
                        patient_data["ethnicity"] = ethnicity
                    if smoking_status:
                        patient_data["smoking_status"] = smoking_status
                    if marital_status:
                        patient_data["marital_status"] = marital_status
                    if employment_status:
                        patient_data["employment_status"] = employment_status
                    if sexual_orientation:
                        patient_data["sexual_orientation"] = sexual_orientation
                    
                    # Family information
                    if mother_first_name:
                        patient_data["mother_first_name"] = mother_first_name
                    if mother_last_name:
                        patient_data["mother_last_name"] = mother_last_name
                    if is_multiple_birth is not None:
                        patient_data["is_multiple_birth"] = is_multiple_birth
                    if birth_order:
                        patient_data["birth_order"] = birth_order
                    
                    # Categories array
                    if categories:
                        patient_data["categories"] = categories
                    
                    # Custom fields
                    if introduction:
                        patient_data["introduction"] = introduction
                    if custom_field_1:
                        patient_data["custom_field_1"] = custom_field_1
                    if custom_field_2:
                        patient_data["custom_field_2"] = custom_field_2
                    if custom_field_3:
                        patient_data["custom_field_3"] = custom_field_3
                    if custom_field_4:
                        patient_data["custom_field_4"] = custom_field_4
                    if custom_field_5:
                        patient_data["custom_field_5"] = custom_field_5
                    
                    # Payment and source information
                    if source_name:
                        patient_data["source_name"] = source_name
                    if source_value:
                        patient_data["source_value"] = source_value
                    if payment_source:
                        patient_data["payment_source"] = payment_source
                    if payment_start_date:
                        patient_data["payment_start_date"] = payment_start_date.isoformat()
                    if payment_end_date:
                        patient_data["payment_end_date"] = payment_end_date.isoformat()
                    
                    # Representative information
                    if rep_first_name:
                        patient_data["rep_first_name"] = rep_first_name
                    if rep_last_name:
                        patient_data["rep_last_name"] = rep_last_name
                    
                    # Control flags
                    if send_phr_invite is not None:
                        patient_data["send_phr_invite"] = send_phr_invite
                    if duplicate_check is not None:
                        patient_data["duplicate_check"] = duplicate_check
                    
                    response = await client.post("/patients", data=patient_data)
                    
                    if response.get("patient"):
                        new_patient_id = response["patient"].get("patient_id")
                        response["guidance"] = f"Patient created successfully with ID: {new_patient_id}. Complete demographic and social history captured. Use reviewPatientHistory('{new_patient_id}') to view full details or manageAppointments() to schedule their first visit."
                    
                    return response
                    
                case "update":
                    if not patient_id:
                        return {
                            "error": "patient_id required for updates",
                            "guidance": "Use findPatients() to locate the patient first, then provide their patient_id."
                        }
                    
                    # Build update data based on update_specific_details flag
                    if update_specific_details:
                        # When using update_specific_details=True, only send the fields that need updating
                        # plus required fields for API call
                        patient_data = {}
                        
                        # Get current patient data to extract required fields
                        current_patient = await client.get(f"/patients/{patient_id}")
                        if not current_patient.get("patient"):
                            return {
                                "error": "Patient not found",
                                "guidance": "Verify the patient_id is correct using findPatients()."
                            }
                        
                        current_data = current_patient["patient"]
                        
                        # Include required fields from current data
                        patient_data["first_name"] = first_name or current_data.get("first_name")
                        patient_data["last_name"] = last_name or current_data.get("last_name")
                        patient_data["gender"] = gender or current_data.get("gender")
                        patient_data["dob"] = date_of_birth.isoformat() if date_of_birth else current_data.get("dob")
                        
                        # Handle facilities requirement
                        if facility_ids:
                            patient_data["facilities"] = [{"facility_id": int(fid)} for fid in facility_ids.split(",")]
                        else:
                            # Use existing facilities
                            patient_data["facilities"] = current_data.get("facilities", [])
                        
                        # Set the update flag
                        patient_data["update_specific_details"] = "true"
                        
                    else:
                        # When update_specific_details=False (default), need to include all existing data
                        # plus any updates to avoid data loss
                        current_patient = await client.get(f"/patients/{patient_id}")
                        if not current_patient.get("patient"):
                            return {
                                "error": "Patient not found",
                                "guidance": "Verify the patient_id is correct using findPatients()."
                            }
                        
                        patient_data = current_patient["patient"].copy()
                        
                        # Remove read-only fields that shouldn't be sent back
                        patient_data.pop("patient_id", None)
                        patient_data.pop("full_name", None)
                        patient_data.pop("is_auto_calculated_dob", None)
                        patient_data.pop("is_active", None)
                        patient_data.pop("is_silhouette", None)
                        patient_data.pop("primary_contact_details", None)
                        
                        # Update fields that were provided
                        if first_name:
                            patient_data["first_name"] = first_name
                        if last_name:
                            patient_data["last_name"] = last_name
                        if gender:
                            patient_data["gender"] = gender
                        if date_of_birth:
                            patient_data["dob"] = date_of_birth.isoformat()
                        if facility_ids:
                            patient_data["facilities"] = [{"facility_id": int(fid)} for fid in facility_ids.split(",")]
                    
                    # Add/update optional fields (for both modes)
                    if age:
                        patient_data["age"] = int(age)
                    if middle_name:
                        patient_data["middle_name"] = middle_name
                    if nick_name:
                        patient_data["nick_name"] = nick_name
                    if suffix:
                        patient_data["suffix"] = suffix
                    if maiden_name:
                        patient_data["maiden_name"] = maiden_name
                    if gender_identity:
                        patient_data["gender_identity"] = gender_identity
                    if record_id:
                        patient_data["record_id"] = record_id
                    
                    # Contact information
                    if phone:
                        patient_data["mobile"] = phone
                    if home_phone:
                        patient_data["home_phone"] = home_phone
                    if work_phone:
                        patient_data["work_phone"] = work_phone
                    if work_phone_extn:
                        patient_data["work_phone_extn"] = work_phone_extn
                    if primary_phone:
                        patient_data["primary_phone"] = primary_phone
                    if email:
                        patient_data["email"] = email
                    
                    # Handle address updates
                    address_fields = [address_line1, address_line2, area, city, state, county_code, zip_code, post_box, district]
                    if any(address_fields):
                        if "address" not in patient_data or not patient_data["address"]:
                            patient_data["address"] = {}
                        if address_line1:
                            patient_data["address"]["address_line1"] = address_line1
                        if address_line2:
                            patient_data["address"]["address_line2"] = address_line2
                        if area:
                            patient_data["address"]["area"] = area
                        if city:
                            patient_data["address"]["city"] = city
                        if state:
                            patient_data["address"]["state"] = state
                        if county_code:
                            patient_data["address"]["county_code"] = county_code
                        if zip_code:
                            patient_data["address"]["zip_code"] = zip_code
                        if post_box:
                            patient_data["address"]["post_box"] = post_box
                        if district:
                            patient_data["address"]["district"] = district
                        patient_data["address"]["country"] = country
                    
                    # Medical and demographic information
                    if blood_group:
                        patient_data["blood_group"] = blood_group
                    if language:
                        patient_data["language"] = language
                    if race:
                        patient_data["race"] = race
                    if ethnicity:
                        patient_data["ethnicity"] = ethnicity
                    if smoking_status:
                        patient_data["smoking_status"] = smoking_status
                    if marital_status:
                        patient_data["marital_status"] = marital_status
                    if employment_status:
                        patient_data["employment_status"] = employment_status
                    if sexual_orientation:
                        patient_data["sexual_orientation"] = sexual_orientation
                    
                    # Family information
                    if mother_first_name:
                        patient_data["mother_first_name"] = mother_first_name
                    if mother_last_name:
                        patient_data["mother_last_name"] = mother_last_name
                    if is_multiple_birth is not None:
                        patient_data["is_multiple_birth"] = is_multiple_birth
                    if birth_order:
                        patient_data["birth_order"] = birth_order
                    
                    # Emergency contact
                    if emergency_contact_name:
                        patient_data["emergency_contact_name"] = emergency_contact_name
                    if emergency_contact_phone:
                        patient_data["emergency_contact_number"] = emergency_contact_phone
                    if emergency_extn:
                        patient_data["emergency_extn"] = emergency_extn
                    
                    # Communication preferences
                    if preferred_communication:
                        patient_data["preferred_communication"] = preferred_communication
                    if email_notification is not None:
                        patient_data["email_notification"] = email_notification
                    if text_notification is not None:
                        patient_data["text_notification"] = text_notification
                    if voice_notification is not None:
                        patient_data["voice_notification"] = voice_notification
                    
                    # Custom fields
                    if introduction:
                        patient_data["introduction"] = introduction
                    if custom_field_1:
                        patient_data["custom_field_1"] = custom_field_1
                    if custom_field_2:
                        patient_data["custom_field_2"] = custom_field_2
                    if custom_field_3:
                        patient_data["custom_field_3"] = custom_field_3
                    if custom_field_4:
                        patient_data["custom_field_4"] = custom_field_4
                    if custom_field_5:
                        patient_data["custom_field_5"] = custom_field_5
                    
                    # Payment information
                    if source_name:
                        patient_data["source_name"] = source_name
                    if source_value:
                        patient_data["source_value"] = source_value
                    if payment_source:
                        patient_data["payment_source"] = payment_source
                    if payment_start_date:
                        patient_data["payment_start_date"] = payment_start_date.isoformat()
                    if payment_end_date:
                        patient_data["payment_end_date"] = payment_end_date.isoformat()
                    
                    # Representative information
                    if rep_first_name:
                        patient_data["rep_first_name"] = rep_first_name
                    if rep_last_name:
                        patient_data["rep_last_name"] = rep_last_name
                    
                    # End of life information
                    if deceased is not None:
                        patient_data["deceased"] = deceased
                    if dod:
                        patient_data["dod"] = dod.isoformat()
                    if cause_of_death:
                        patient_data["cause_of_death"] = cause_of_death
                    
                    # Complex relationships
                    if categories:
                        patient_data["categories"] = categories
                    if caregivers:
                        patient_data["caregivers"] = caregivers
                    if guarantor:
                        patient_data["guarantor"] = guarantor
                    if linked_patient_id:
                        patient_data["linked_patient_id"] = linked_patient_id
                    if id_qualifiers:
                        patient_data["id_qualifiers"] = id_qualifiers
                    
                    # Control flags
                    if send_phr_invite is not None:
                        patient_data["send_phr_invite"] = send_phr_invite
                    if duplicate_check is not None:
                        patient_data["duplicate_check"] = duplicate_check
                    
                    response = await client.put(f"/patients/{patient_id}", data=patient_data)
                    
                    if response.get("patient"):
                        update_mode = "specific fields" if update_specific_details else "complete record"
                        response["guidance"] = f"Patient {patient_id} updated successfully ({update_mode}). Use reviewPatientHistory('{patient_id}') to see the updated information."
                    
                    return response
                    
                case "activate":
                    if not patient_id:
                        return {
                            "error": "patient_id required for activation",
                            "guidance": "Use findPatients() to locate the patient first."
                        }
                    
                    response = await client.post(f"/patients/{patient_id}/active")
                    if response.get("code") == 200:
                        response["guidance"] = f"Patient {patient_id} activated successfully. They can now receive care and schedule appointments."
                    
                    return response
                    
                case "deactivate":
                    if not patient_id:
                        return {
                            "error": "patient_id required for deactivation",
                            "guidance": "Use findPatients() to locate the patient first."
                        }
                    
                    response = await client.post(f"/patients/{patient_id}/inactive")
                    if response.get("code") == 200:
                        response["guidance"] = f"Patient {patient_id} deactivated. Use action='activate' to reactivate them later."
                    
                    return response
                    
        except Exception as e:
            logger.error(f"Error in managePatient: {e}")
            return {
                "error": str(e),
                "guidance": f"Operation '{action}' failed. Check your parameters and try again. For creation, ensure all required fields are provided."
            }

@charm_mcp.tool
@with_tool_metrics()
async def reviewPatientHistory(
    patient_id: str,
    include_sections: Optional[List[Literal["demographics", "vitals", "medications", "allergies", "diagnoses", "encounters", "appointments"]]] = None
) -> Dict[str, Any]:
    """
    <usecase>
    Get comprehensive patient information including medical history, current medications, recent visits.
    Perfect for clinical decision-making and preparing for patient encounters.
    </usecase>
    
    <instructions>
    Returns a consolidated view of patient information organized by medical relevance.
    By default includes all sections (include_sections=None). Specify include_sections to focus on specific areas.
    Results include clinical context and suggestions for next actions.

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            if include_sections is None:
                include_sections = ["demographics", "vitals", "medications", "allergies", "diagnoses", "encounters", "appointments"]
            
            patient_summary = {"patient_id": patient_id}
            
            # Get basic patient info
            if "demographics" in include_sections:
                patient_response = await client.get(f"/patients/{patient_id}")
                if patient_response.get("patient"):
                    patient_summary["demographics"] = patient_response["patient"]
            
            # Get current medications
            if "medications" in include_sections:
                meds_response = await client.get(f"/patients/{patient_id}/medications")
                patient_summary["current_medications"] = meds_response.get("medications", [])
            
            # Get allergies
            if "allergies" in include_sections:
                allergies_response = await client.get(f"/patients/{patient_id}/allergies")
                patient_summary["allergies"] = allergies_response.get("allergies", [])
            
            # Get recent vitals
            if "vitals" in include_sections:
                vitals_response = await client.get(f"/patients/{patient_id}/vitals", params={"limit": 10})
                patient_summary["recent_vitals"] = vitals_response.get("vitals", [])
            
            # Get active diagnoses
            if "diagnoses" in include_sections:
                diagnoses_response = await client.get(f"/patients/{patient_id}/diagnoses")
                patient_summary["diagnoses"] = diagnoses_response.get("patient_diagnoses", [])
            
            # Get recent encounters (last 10)
            if "encounters" in include_sections:
                encounters_response = await client.get("/encounters", params={
                    "patient_id": patient_id,
                    "per_page": 10,
                    "sort_order": "D"
                })
                patient_summary["recent_encounters"] = encounters_response.get("encounters", [])
            
            # Get upcoming appointments
            if "appointments" in include_sections:
                from datetime import datetime, timedelta
                today = datetime.now().date()
                future_date = today + timedelta(days=90)
                
                appointments_response = await client.get("/appointments", params={
                    "patient_id": patient_id,
                    "start_date": today.strftime("%Y-%m-%d"),
                    "end_date": future_date.strftime("%Y-%m-%d"),
                    "facility_ids": "ALL"
                })
                patient_summary["upcoming_appointments"] = appointments_response.get("appointments", [])
            
            # Add clinical insights
            insights = []
            
            if patient_summary.get("allergies"):
                allergy_count = len(patient_summary["allergies"])
                insights.append(f"Patient has {allergy_count} documented allergies - review before prescribing")
            
            if patient_summary.get("current_medications"):
                med_count = len(patient_summary["current_medications"])
                insights.append(f"Patient currently on {med_count} medications - check for interactions")
            
            if patient_summary.get("recent_vitals"):
                vital_count = len(patient_summary["recent_vitals"])
                insights.append(f"Patient has {vital_count} recent vital sign records - review trends for clinical changes")
            
            if patient_summary.get("upcoming_appointments"):
                next_appt = patient_summary["upcoming_appointments"][0] if patient_summary["upcoming_appointments"] else None
                if next_appt:
                    insights.append(f"Next appointment: {next_appt.get('appointment_date')} - use documentEncounter() after visit")
            
            patient_summary["clinical_insights"] = insights
            
            # Generate workflow-specific guidance
            workflow_guidance = []
            
            # Safety-first guidance
            if patient_summary.get("allergies"):
                workflow_guidance.append("⚠️ Review allergies before prescribing with managePatientDrugs()")
            else:
                workflow_guidance.append("Consider checking allergies with managePatientAllergies() before prescribing")
            
            # Clinical action guidance based on data
            if patient_summary.get("diagnoses"):
                active_dx = [d for d in patient_summary["diagnoses"] if d.get("status", "").lower() == "active"]
                if active_dx:
                    workflow_guidance.append(f"Patient has {len(active_dx)} active diagnoses - consider treatment adjustments")
            
            # Next appointment guidance
            if patient_summary.get("upcoming_appointments"):
                next_appt = patient_summary["upcoming_appointments"][0]
                workflow_guidance.append(f"Next visit: {next_appt.get('appointment_date')} - prepare encounter with documentEncounter()")
            else:
                workflow_guidance.append("No upcoming appointments - schedule follow-up with managePatientAppointments() if needed")
            
            # Medication review guidance
            if patient_summary.get("current_medications"):
                workflow_guidance.append("Review medication compliance and interactions")
            
            # Vitals review guidance
            if patient_summary.get("recent_vitals"):
                workflow_guidance.append("Review vital sign trends with managePatientVitals() for clinical monitoring")
            else:
                workflow_guidance.append("Consider recording current vitals with managePatientVitals() during next encounter")
            
            patient_summary["workflow_guidance"] = workflow_guidance
            patient_summary["guidance"] = "Clinical review complete. " + "; ".join(workflow_guidance[:2]) + "."
            
            logger.info(f"reviewPatientHistory completed for patient {patient_id}")
            return patient_summary
            
        except Exception as e:
            logger.error(f"Error in reviewPatientHistory: {e}")
            return {
                "error": str(e),
                "guidance": "Failed to retrieve patient history. Verify patient_id using findPatients() first."
            }

@charm_mcp.tool 
@with_tool_metrics()
async def managePatientDrugs(
    action: Literal["add", "update", "discontinue", "list"],
    patient_id: str,
    substance_type: Literal["medication", "supplement", "vitamin"] = "medication",
    record_id: Optional[str] = None,
    
    # Common drug fields
    drug_name: Optional[str] = None,
    dosage: Optional[str] = None,
    strength: Optional[str] = None,
    frequency: Optional[str] = None,
    directions: Optional[str] = None,
    refills: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    status: Optional[Literal["active", "inactive"]] = "active",
    encounter_id: Optional[str] = None,
    
    # Additional supplement fields
    route: Optional[str] = None,
    dose_form: Optional[str] = None,
    dosage_unit: Optional[str] = None,
    quantity: Optional[int] = None,
    intake_type: Optional[str] = None,
    comments: Optional[str] = None,
    weaning_schedule: Optional[str] = None,
    
    # Workflow fields
    check_allergies: Optional[bool] = True,
) -> Dict[str, Any]:
    """
    <usecase>
    Unified drug management for medications, supplements, and vitamins - prescribe medications, 
    document supplements, manage drug interactions. Includes automatic allergy checking and 
    comprehensive drug safety workflow for optimal patient care.
    </usecase>
    
    <instructions>
    Actions:
    - "add": Prescribe new drug (requires drug_name, directions for medications; drug_name, dosage for supplements)
    - "update": Modify existing prescription (requires record_id + fields to change)  
    - "discontinue": Stop drug (requires record_id)
    - "list": Show all patient drugs by type (optionally filter by substance_type)
    
    Substance Types:
    - "medication": Prescription drugs (requires directions, refills)
    - "supplement": OTC supplements/vitamins (requires dosage as integer)
    - "vitamin": Specific vitamins (requires dosage as integer)
    
    Safety: Automatically checks allergies before prescribing unless check_allergies=False
    For medications: Use clear directions like "Take 1 tablet by mouth twice daily with food"
    For supplements: Provide dosage as integer (e.g., 5) and use strength for units (e.g., "500mg")

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Safety check: Review allergies before prescribing
            if action == "add" and check_allergies:
                allergy_response = await client.get(f"/patients/{patient_id}/allergies")
                if allergy_response.get("allergies"):
                    allergies = allergy_response["allergies"]
                    if allergies and substance_type == "medication":
                        allergy_warning = f"⚠️ Patient has {len(allergies)} documented allergies. Review before prescribing: "
                        allergy_list = [a.get("allergen", "Unknown") for a in allergies[:3]]
                        allergy_warning += ", ".join(allergy_list)
                        if len(allergies) > 3:
                            allergy_warning += f" and {len(allergies) - 3} more"
                        logger.warning(allergy_warning)
            
            match action:
                case "list":
                    if substance_type in ["medication"]:
                        response = await client.get(f"/patients/{patient_id}/medications")
                        if response.get("medications"):
                            med_count = len(response["medications"])
                            active_meds = [med for med in response["medications"] if med.get("is_active")]
                            response["guidance"] = f"Patient has {med_count} total medications, {len(active_meds)} active. Check managePatientAllergies() before prescribing new drugs."
                    else:
                        # Get supplements
                        response = await client.get(f"/patients/{patient_id}/supplements")
                        if response.get("supplements"):
                            supp_count = len(response["supplements"])
                            active_supps = [s for s in response["supplements"] if s.get("status") == "Active"]
                            response["guidance"] = f"Patient has {supp_count} total supplements/vitamins, {len(active_supps)} active. Use action='add' to document new supplements."
                    
                    return response
                    
                case "add":
                    if substance_type == "medication":
                        # Prescription medication
                        required = [drug_name, directions]
                        if not all(required):
                            return {
                                "error": "Missing required fields for medication",
                                "guidance": "For medications, provide: drug_name and directions. Example: drug_name='Lisinopril 10mg', directions='Take 1 tablet by mouth once daily'. Check allergies first with managePatientAllergies()."
                            }
                        
                        med_data = [{
                            "drug_name": drug_name,
                            "is_active": status == "active",
                            "directions": directions,
                            "dispense": 30.0,  # Default 30-day supply
                            "refills": refills or "0",
                            "substitute_generic": True,
                            "manufacturing_type": "Manufactured"
                        }]
                        
                        if strength:
                            med_data[0]["strength_description"] = strength
                        if start_date:
                            med_data[0]["start_date"] = start_date.isoformat()
                        if end_date:
                            med_data[0]["stop_date"] = end_date.isoformat()
                        
                        response = await client.post(f"/patients/{patient_id}/medications", data=med_data)
                        
                        if response.get("medications"):
                            response["guidance"] = f"Medication '{drug_name}' prescribed successfully. Monitor for allergic reactions and drug interactions. Use reviewPatientHistory() to see all current medications."
                    
                    else:
                        # Supplement/vitamin
                        required = [drug_name, dosage]
                        if not all(required):
                            return {
                                "error": "Missing required fields for supplement",
                                "guidance": "For supplements/vitamins, provide: drug_name and dosage. Example: drug_name='Vitamin D3', dosage=5 (as integer)"
                            }
                        
                        # Ensure dosage is an integer as required by API
                        try:
                            dosage_int = int(dosage) if isinstance(dosage, str) else dosage
                        except (ValueError, TypeError):
                            return {
                                "error": "Dosage must be a valid integer",
                                "guidance": "Provide dosage as an integer value (e.g., dosage=5, not dosage='5mg'). Use strength field for units like 'mg' or 'IU'."
                            }
                        
                        supplement_data = [{
                            "supplement_name": drug_name,
                            "dosage": dosage_int,
                            "supplement_type": "Manufactured",
                            "status": status.title() if status else "Active"
                        }]
                        
                        # Add optional fields only if provided
                        if strength:
                            supplement_data[0]["strength"] = strength
                        if start_date:
                            supplement_data[0]["start_date"] = start_date.isoformat()
                        if end_date:
                            supplement_data[0]["end_date"] = end_date.isoformat()
                        if frequency:
                            supplement_data[0]["frequency"] = frequency
                        if intake_type:
                            supplement_data[0]["intake_type"] = intake_type
                        if refills:
                            supplement_data[0]["refills"] = int(refills) if isinstance(refills, str) else refills
                        if route:
                            supplement_data[0]["route"] = route
                        if dose_form:
                            supplement_data[0]["dose_form"] = dose_form
                        if dosage_unit:
                            supplement_data[0]["dosage_unit"] = dosage_unit
                        if quantity:
                            supplement_data[0]["quantity"] = int(quantity) if isinstance(quantity, str) else quantity
                        if comments:
                            supplement_data[0]["comments"] = comments
                        if weaning_schedule:
                            supplement_data[0]["weaning_schedule"] = weaning_schedule
                        if encounter_id:
                            supplement_data[0]["encounter_id"] = int(encounter_id) if isinstance(encounter_id, str) else encounter_id
                        if directions:  # Use directions as comments if no explicit comments provided
                            if not comments:
                                supplement_data[0]["comments"] = directions
                        
                        response = await client.post(f"/patients/{patient_id}/supplements", data=supplement_data)
                        
                        if response.get("supplements"):
                            response["guidance"] = f"Supplement '{drug_name}' documented successfully. This will appear in the patient's medication list for reference during prescribing."
                    
                    return response
                    
                case "update":
                    if not record_id:
                        return {
                            "error": "record_id required for updates",
                            "guidance": "Use action='list' to find the medication/supplement record_id first."
                        }
                    
                    if substance_type == "medication":
                        update_data = {}
                        if drug_name:
                            update_data["drug_name"] = drug_name
                        if directions:
                            update_data["directions"] = directions
                        if refills:
                            update_data["refills"] = refills
                        if status:
                            update_data["is_active"] = status == "active"
                        if strength:
                            update_data["strength_description"] = strength
                        
                        response = await client.put(f"/patients/{patient_id}/medications/{record_id}", data=update_data)
                        
                        if response.get("medications"):
                            response["guidance"] = f"Medication {record_id} updated successfully. Changes are now active in the patient's medication profile."
                    else:
                        # Update supplement
                        update_data = {}
                        if drug_name:
                            update_data["supplement_name"] = drug_name
                        if dosage:
                            update_data["dosage"] = dosage
                        if strength:
                            update_data["strength"] = strength
                        if status:
                            update_data["status"] = status.title()
                        if frequency:
                            update_data["frequency"] = frequency
                        
                        response = await client.put(f"/patients/{patient_id}/supplements/{record_id}", data=update_data)
                        
                        if response.get("supplements"):
                            response["guidance"] = f"Supplement {record_id} updated successfully. Changes are reflected in the patient's supplement list."
                    
                    return response
                    
                case "discontinue":
                    if not record_id:
                        return {
                            "error": "record_id required to discontinue drug",
                            "guidance": "Use action='list' to find the medication/supplement record_id first."
                        }
                    
                    if substance_type == "medication":
                        # Set medication to inactive
                        response = await client.put(f"/patients/{patient_id}/medications/{record_id}", data={"is_active": False})
                        
                        if response.get("medications"):
                            response["guidance"] = f"Medication {record_id} discontinued. Patient should stop taking this medication. Document discontinuation reason in next encounter with documentEncounter()."
                    else:
                        # Set supplement to inactive
                        response = await client.put(f"/patients/{patient_id}/supplements/{record_id}", data={"status": "Inactive"})
                        
                        if response.get("supplements"):
                            response["guidance"] = f"Supplement {record_id} discontinued. This supplement is no longer part of the patient's active regimen."
                    
                    return response
                
        except Exception as e:
            logger.error(f"Error in managePatientDrugs: {e}")
            return {
                "error": str(e), 
                "guidance": f"Drug {action} failed for {substance_type}. For safety, always check allergies with managePatientAllergies() before prescribing medications."
            }

@charm_mcp.tool
@with_tool_metrics()
async def managePatientVitals(
    action: Literal["add", "list", "update"],
    patient_id: str,
    encounter_id: Optional[str] = None,
    record_id: Optional[str] = None,
    
    # Vital signs data - can provide as dict or individual fields
    vitals: Optional[Dict[str, str]] = None,
    
    # Individual vital fields
    vital_name: Optional[str] = None,
    vital_value: Optional[str] = None,
    vital_unit: Optional[str] = None,
    
    # Filtering for list action
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: Optional[int] = 50,
) -> Dict[str, Any]:
    """
    <usecase>
    Complete patient vital signs management - record vitals during encounters, review vital trends,
    update incorrect readings, and track patient health metrics over time. Essential for clinical monitoring.
    </usecase>
    
    <instructions>
    Actions:
    - "add": Record new vitals (requires patient_id + encounter_id + vitals dict OR individual vital fields). Check available vitals with getPracticeInfo(info_type='vitals') first to ensure all vital names and units are correct.
    - "list": Show patient vital history (optionally filter by date range)
    - "update": Modify existing vital record (requires record_id + fields to change)
    - "delete": Remove incorrect vital record (requires record_id)
    
    Vitals Format: 
    - As dict: {"Weight": "70 kg", "BP": "120/80 mmHg", "Pulse": "72 bpm", "Temperature": "98.6 F"}
    - Individual: vital_name="Weight", vital_value="70", vital_unit="kg"
    
    Common Vitals: Weight, Height, Blood Pressure (BP), Pulse Rate, Temperature, Respiratory Rate, Oxygen Saturation
    Use getPracticeInfo(info_type='vitals') to see available vital types and proper naming

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            match action:
                case "list":
                    params = {}
                    if start_date:
                        params["start_date"] = start_date.strftime("%Y-%m-%d")
                    if end_date:
                        params["end_date"] = end_date.strftime("%Y-%m-%d")
                    if limit:
                        params["limit"] = limit
                    
                    response = await client.get(f"/patients/{patient_id}/vitals", params=params)
                    
                    if response.get("vitals"):
                        vital_count = len(response["vitals"])
                        date_range = ""
                        if start_date and end_date:
                            date_range = f" from {start_date} to {end_date}"
                        elif start_date:
                            date_range = f" since {start_date}"
                        
                        response["guidance"] = f"Found {vital_count} vital sign records{date_range}. Use this data to track patient health trends and clinical progress."
                    else:
                        response["guidance"] = "No vital signs found for this patient. Use action='add' to record vitals during encounters."
                    
                    return response
                    
                case "add":
                    if not encounter_id:
                        return {
                            "error": "encounter_id required for adding vitals",
                            "guidance": "Vitals must be linked to an encounter. Use documentEncounter() first to create an encounter, then record vitals."
                        }
                    
                    vitals_list = []
                    
                    # Handle vitals dict format
                    if vitals:
                        for vital_name_key, vital_value_with_unit in vitals.items():
                            # Parse value and unit
                            parts = vital_value_with_unit.split()
                            value = parts[0] if parts else vital_value_with_unit
                            unit = " ".join(parts[1:]) if len(parts) > 1 else ""
                            
                            vitals_list.append({
                                "vital_name": vital_name_key,
                                "vital_value": value,
                                "vital_unit": unit
                            })
                    
                    # Handle individual vital fields
                    elif vital_name and vital_value:
                        vitals_list.append({
                            "vital_name": vital_name,
                            "vital_value": vital_value,
                            "vital_unit": vital_unit or ""
                        })
                    else:
                        return {
                            "error": "Either vitals dict or individual vital fields required",
                            "guidance": "Provide vitals as dict like {'Weight': '70 kg', 'BP': '120/80 mmHg'} OR individual fields (vital_name, vital_value, vital_unit)."
                        }
                    
                    if not vitals_list:
                        return {
                            "error": "No valid vitals data provided",
                            "guidance": "Check your vitals format. Use getPracticeInfo(info_type='vitals') to see available vital types."
                        }
                    
                    vitals_data = [{
                        "encounter_id": encounter_id,
                        "vitals": vitals_list
                    }]
                    
                    response = await client.post(f"/patients/{patient_id}/vitals", data=vitals_data)
                    
                    if response.get("vitals"):
                        recorded_vitals = [v["vital_name"] for v in vitals_list]
                        response["guidance"] = f"Vitals recorded successfully: {', '.join(recorded_vitals)}. These are now part of the patient's clinical record for encounter {encounter_id}."
                    else:
                        response["guidance"] = "Vitals recording failed. Verify encounter_id exists and vital names match practice standards. Use getPracticeInfo(info_type='vitals') for valid vital types."
                    
                    return response
                    
                case "update":
                    if not record_id:
                        return {
                            "error": "record_id required for updates",
                            "guidance": "Use action='list' to find the vital record_id first."
                        }
                    
                    # Build vitals list for update
                    vitals_list = []
                    
                    # Handle vitals dict format
                    if vitals:
                        for vital_name_key, vital_value_with_unit in vitals.items():
                            # Parse value and unit
                            parts = vital_value_with_unit.split()
                            value = parts[0] if parts else vital_value_with_unit
                            unit = " ".join(parts[1:]) if len(parts) > 1 else ""
                            
                            vitals_list.append({
                                "vital_name": vital_name_key,
                                "vital_value": value,
                                "vital_unit": unit
                            })
                    
                    # Handle individual vital fields
                    elif vital_name and vital_value:
                        vitals_list.append({
                            "vital_name": vital_name,
                            "vital_value": vital_value,
                            "vital_unit": vital_unit or ""
                        })
                    else:
                        return {
                            "error": "Either vitals dict or individual vital fields required for update",
                            "guidance": "Provide vitals as dict like {'Weight': '70 kg', 'BP': '120/80 mmHg'} OR individual fields (vital_name, vital_value, vital_unit)."
                        }
                    
                    if not vitals_list:
                        return {
                            "error": "No valid vitals data provided for update",
                            "guidance": "Check your vitals format. Use getPracticeInfo(info_type='vitals') to see available vital types."
                        }
                    
                    # Build update data structure as per API specification
                    update_data = {
                        "vitals": vitals_list
                    }
                    
                    # Add encounter_id if provided (optional for vitals part of an encounter)
                    if encounter_id:
                        update_data["encounter_id"] = encounter_id
                    
                    response = await client.put(f"/patients/{patient_id}/vitals/{record_id}", data=update_data)
                    
                    if response.get("vitals"):
                        updated_vitals = [v["vital_name"] for v in vitals_list]
                        response["guidance"] = f"Vital record {record_id} updated successfully: {', '.join(updated_vitals)}. The corrected vital signs are now in the patient's record."
                    else:
                        response["guidance"] = "Vital update failed. Verify the record_id exists and the new values are valid."
                    
                    return response
                
                    
        except Exception as e:
            logger.error(f"Error in managePatientVitals: {e}")
            return {
                "error": str(e),
                "guidance": f"Vitals {action} failed. Ensure patient_id and encounter_id are valid. Use getPracticeInfo(info_type='vitals') to verify vital naming conventions."
            }

@charm_mcp.tool
@with_tool_metrics()
async def documentEncounter(
    patient_id: str,
    provider_id: str,
    facility_id: str,
    encounter_date: date,
    appointment_id: Optional[str] = None,
    visit_type_id: Optional[str] = None,
    encounter_mode: Optional[Literal["In Person", "Phone Call", "Video Consult"]] = "In Person",
    chief_complaint: Optional[str] = None
) -> Dict[str, Any]:
    """
    <usecase>
    Complete encounter documentation workflow - create encounter and record comprehensive clinical findings
    with extensive SOAP note capabilities and specialized clinical sections. For vitals, use managePatientVitals().
    </usecase>
    
    <instructions>
    Can create encounter from existing appointment (provide appointment_id) or create new encounter. IMPORTANT: If creating a new encounter, you must provide the following: provider_id, facility_id, encounter_date, and encounter_mode.
    For clinical notes: Use clear, professional medical language
    For vitals: Use managePatientVitals() after creating the encounter to record vital signs
    For diagnoses: Use manageDiagnoses() to add new diagnoses, update existing conditions, and maintain accurate medical problem lists.
    
    Clinical Documentation Sections:
    - chief_complaint: Primary reason for visit

    
    Tool will guide you through the complete documentation workflow step by step.

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            encounter_response = None
            
            # Step 1: Create encounter
            if appointment_id:
                # Create from existing appointment
                encounter_response = await client.post(
                    f"/appointments/{appointment_id}/encounter",
                    data={"chart_type": "SOAP"}
                )
            else:
                # Create new encounter
                encounter_data = {
                    "provider_id": provider_id,
                    "facility_id": facility_id,
                    "date": encounter_date.isoformat(),
                    "chart_type": "SOAP",
                    "encounter_mode": encounter_mode
                }
                if visit_type_id:
                    encounter_data["visittype_id"] = visit_type_id
                encounter_response = await client.post(f"/patients/{patient_id}/encounter", data=encounter_data)
            
            if not encounter_response.get("encounter"):
                return {
                    "error": "Failed to create encounter",
                    "guidance": "Check that patient_id and provider_id are valid. If using appointment_id, verify the appointment exists and hasn't been converted to an encounter already."
                }
            encounter_id = encounter_response["encounter"].get("encounter_id")
            documentation_steps = [f"✓ Encounter created (ID: {encounter_id})"]
            
            # Step 2: Save clinical documentation
            clinical_notes = {}
            if chief_complaint:
                clinical_notes["chief_complaints"] = chief_complaint
            if clinical_notes:
                notes_response = await client.post(
                    f"/patients/{patient_id}/encounters/{encounter_id}/save",
                    data=clinical_notes
                )
                if notes_response.get("notes"):
                    documentation_steps.append("✓ Clinical notes saved")
            
            # Prepare response with guidance
            result = {
                "encounter_id": encounter_id,
                "documentation_completed": documentation_steps,
                "guidance": f"Encounter documented successfully. Next steps: Use managePatientVitals() to record vital signs, managePatientDrugs() to update prescriptions, add diagnoses with managePatientDiagnoses(), or schedule follow-up with managePatientAppointments()."
            }
            return result
            
        except Exception as e:
            logger.error(f"Error in documentEncounter: {e}")
            return {
                "error": str(e),
                "guidance": "Encounter documentation failed. Ensure patient_id and provider_id are valid. If using appointment_id, verify the appointment exists and is ready for documentation."
            }

@charm_mcp.tool
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

@charm_mcp.tool
@with_tool_metrics()
async def managePatientAllergies(
    action: Literal["add", "list", "update", "delete"],
    patient_id: str,
    record_id: Optional[str] = None,
    
    # Allergy fields
    allergen: Optional[str] = None,
    allergy_type: Optional[str] = None,
    severity: Optional[str] = None,
    reactions: Optional[str] = None,
    allergy_status: Optional[str] = None,
    allergy_date: Optional[date] = None,
    comments: Optional[str] = None,
) -> Dict[str, Any]:
    """
    <usecase>
    Critical allergy management with safety alerts - document patient allergies, update allergy information,
    and maintain allergy safety checks. Essential for safe prescribing and clinical decision-making.
    </usecase>
    
    <instructions>
    Actions:
    - "add": Document new allergy (requires allergen, allergy_type, severity, reactions, allergy_date)
    - "list": Show all patient allergies (requires only patient_id)
    - "update": Modify existing allergy (requires record_id + fields to change)
    - "delete": Remove allergy record (requires record_id)
    
    Safety critical: Always check allergies before prescribing medications.
    Common allergens: "Penicillin", "Latex", "Shellfish", "Nuts", "Contrast dye"
    Severity levels: "Mild", "Moderate", "Severe", "Life-threatening"

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            match action:
                case "list":
                    response = await client.get(f"/patients/{patient_id}/allergies")
                    if response.get("allergies"):
                        allergy_count = len(response["allergies"])
                        severe_allergies = [a for a in response["allergies"] if a.get("severity", "").lower() in ["severe", "life-threatening"]]
                        
                        guidance = f"Patient has {allergy_count} documented allergies"
                        if severe_allergies:
                            guidance += f", including {len(severe_allergies)} severe/life-threatening allergies"
                        guidance += ". CRITICAL: Review all allergies before prescribing with manageMedications() or managePatientDrugs()."
                        response["guidance"] = guidance
                    else:
                        response["guidance"] = "No allergies documented. Before prescribing medications, confirm with patient if they have any known allergies."
                    return response
                    
                case "add":
                    required = [allergen, allergy_type, severity, reactions, allergy_date]
                    if not all(required):
                        return {
                            "error": "Missing required fields for allergy",
                            "guidance": "For allergies, provide: allergen, allergy_type, severity, reactions, and allergy_date. This is critical safety information."
                        }
                    
                    allergy_data = {
                        "allergen": allergen,
                        "type": allergy_type,
                        "severity": severity,
                        "reactions": reactions,
                        "date": allergy_date.isoformat(),
                        "status": allergy_status or "Active"
                    }
                    
                    if comments:
                        allergy_data["comments"] = comments
                    
                    response = await client.post(f"/patients/{patient_id}/allergies", data=allergy_data)
                    if response.get("patient_allergy"):
                        severity_warning = ""
                        if severity.lower() in ["severe"]:
                            severity_warning = " ⚠️ SEVERE ALLERGY ALERT: This will trigger warnings during prescribing."
                        response["guidance"] = f"Allergy to '{allergen}' documented successfully.{severity_warning} All providers will see this allergy alert when prescribing medications."
                    return response
                    
                case "update":
                    if not record_id:
                        return {
                            "error": "record_id required for updates",
                            "guidance": "Use action='list' to find the allergy record_id first."
                        }
                    
                    update_data = {}
                    if allergen:
                        update_data["allergen"] = allergen
                    if allergy_type:
                        update_data["type"] = allergy_type
                    if severity:
                        update_data["severity"] = severity
                    if reactions:
                        update_data["reactions"] = reactions
                    if allergy_status:
                        update_data["status"] = allergy_status
                    if allergy_date:
                        update_data["date"] = allergy_date.isoformat()
                    if comments:
                        update_data["comments"] = comments
                    
                    response = await client.put(f"/patients/{patient_id}/allergies/{record_id}", data=update_data)
                    if response.get("patient_allergy"):
                        response["guidance"] = f"Allergy record {record_id} updated successfully. Updated allergy information is now active in safety alerts."
                    return response
                    
                case "delete":
                    if not record_id:
                        return {
                            "error": "record_id required for deletion",
                            "guidance": "Use action='list' to find the allergy record_id first."
                        }
                    
                    response = await client.delete(f"/patients/{patient_id}/allergies/{record_id}")
                    if response.get("code") == "0":
                        response["guidance"] = f"Allergy record {record_id} deleted successfully. This allergy will no longer appear in clinical alerts. Ensure this is correct before prescribing."
                    return response
                    
        except Exception as e:
            logger.error(f"Error in managePatientAllergies: {e}")
            return {
                "error": str(e),
                "guidance": f"Allergy {action} failed. This is critical safety information - ensure allergies are properly documented before any prescribing."
            }

@charm_mcp.tool
@with_tool_metrics()
async def managePatientDiagnoses(
    action: Literal["add", "list", "update", "delete"],
    patient_id: str,
    record_id: Optional[str] = None,
    
    # Diagnosis fields  
    diagnosis_name: Optional[str] = None,
    diagnosis_code: Optional[str] = None,
    code_type: Optional[Literal["ICD10", "SNOMED"]] = None,
    diagnosis_status: Optional[Literal["Active", "Inactive", "Resolved"]] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    encounter_id: Optional[str] = None,
    diagnosis_order: Optional[int] = None,
    comments: Optional[str] = None,
) -> Dict[str, Any]:
    """
    <usecase>
    Complete diagnosis management for patient problem lists - add new diagnoses, update existing conditions,
    and maintain accurate medical problem lists. Essential for clinical reasoning and care planning.
    </usecase>
    
    <instructions>
    Actions:
    - "add": Add new diagnosis (requires diagnosis_name, diagnosis_code, code_type)
    - "list": Show all patient diagnoses (optionally filter by encounter_id)
    - "update": Modify existing diagnosis (requires record_id + fields to change)
    - "delete": Remove diagnosis (requires record_id). Ask the user if they are sure they want to delete the diagnosis before proceeding.
    
    Code types: "ICD10", "SNOMED"
    Status options: "Active", "Inactive", "Resolved"
    Use encounter_id to link diagnosis to specific visit for billing and documentation

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            match action:
                case "list":
                    params = {}
                    if encounter_id:
                        params["encounter_id"] = int(encounter_id)
                    
                    endpoint = f"/patients/{patient_id}/diagnoses"
                    if params:
                        endpoint += "?" + "&".join([f"{k}={v}" for k, v in params.items()])
                    
                    response = await client.get(endpoint)
                    if response.get("diagnoses"):
                        dx_count = len(response["diagnoses"])
                        active_dx = [d for d in response["diagnoses"] if d.get("status", "").lower() == "active"]
                        
                        guidance = f"Patient has {dx_count} documented diagnoses, {len(active_dx)} active"
                        if encounter_id:
                            guidance += f" (filtered by encounter {encounter_id})"
                        guidance += ". Use manageMedications() or managePatientDrugs() to prescribe treatments for active diagnoses."
                        response["guidance"] = guidance
                    else:
                        response["guidance"] = "No diagnoses found. Use action='add' to document patient conditions for proper care planning."
                    return response
                    
                case "add":
                    required = [diagnosis_name, diagnosis_code, code_type]
                    if not all(required):
                        return {
                            "error": "Missing required fields for diagnosis",
                            "guidance": "For diagnoses, provide: diagnosis_name, diagnosis_code, and code_type (e.g., 'ICD10'). This ensures proper medical coding and billing."
                        }
                    
                    diagnosis_data = [{
                        "name": diagnosis_name,
                        "code": diagnosis_code,
                        "code_type": code_type,
                        "status": diagnosis_status or "Active"
                    }]
                    if diagnosis_order:
                        diagnosis_data[0]["diagnosis_order"] = diagnosis_order
                    if encounter_id:
                        diagnosis_data[0]["encounter_id"] = int(encounter_id)
                    if comments:
                        diagnosis_data[0]["comments"] = comments
                    if from_date:
                        diagnosis_data[0]["from_date"] = from_date
                    if to_date:
                        diagnosis_data[0]["to_date"] = to_date
                    if diagnosis_order:
                        diagnosis_data[0]["diagnosis_order"] = str(diagnosis_order)
                    logger.info(f"Diagnosis data: {diagnosis_data}")
                    response = await client.post(f"/patients/{patient_id}/diagnoses", data=diagnosis_data)
                    logger.info(f"Diagnosis response: {response}")
                    if response.get("patient_diagnoses"):
                        guidance = f"Diagnosis '{diagnosis_name}' ({diagnosis_code}) added successfully to problem list."
                        if encounter_id:
                            guidance += f" Linked to encounter {encounter_id} for billing."
                        guidance += " Consider appropriate treatments (medications, supplements, etc.) with managePatientDrugs() or schedule follow-up with managePatientAppointments()."
                        response["guidance"] = guidance
                    return response
                    
                case "update":
                    if not record_id:
                        return {
                            "error": "record_id required for updates",
                            "guidance": "Use action='list' to find the diagnosis record_id first."
                        }
                    
                    update_data = {}
                    if diagnosis_status:
                        update_data["status"] = diagnosis_status
                    if comments:
                        update_data["comments"] = comments
                    if from_date:
                        update_data["from_date"] = from_date
                    if to_date:
                        update_data["to_date"] = to_date
                    
                    response = await client.put(f"/patients/{patient_id}/diagnoses/{record_id}", data=update_data)
                    if response.get("patient_diagnoses"):
                        status_msg = f" Status updated to '{diagnosis_status}'." if diagnosis_status else ""
                        response["guidance"] = f"Diagnosis {record_id} updated successfully.{status_msg} Changes are reflected in the patient's active problem list."
                    return response
                    
                case "delete":
                    if not record_id:
                        return {
                            "error": "record_id required for deletion",
                            "guidance": "Use action='list' to find the diagnosis record_id first."
                        }
                    
                    response = await client.delete(f"/patients/{patient_id}/diagnoses/{record_id}")
                    if response.get("code") == "0":
                        response["guidance"] = f"Diagnosis {record_id} removed from problem list. Ensure this doesn't affect ongoing treatment plans."
                    return response
                    
        except Exception as e:
            logger.error(f"Error in managePatientDiagnoses: {e}")
            return {
                "error": str(e),
                "guidance": f"Diagnosis {action} failed. Accurate diagnosis documentation is essential for proper patient care and billing."
            }

@charm_mcp.tool
@with_tool_metrics()
async def managePatientNotes(
    action: Literal["add", "list", "update", "delete"],
    patient_id: str,
    record_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    <usecase>
    Quick clinical note management for important patient information - add care notes, provider communications,
    and clinical observations that need to be highlighted across all patient interactions.
    </usecase>
    
    <instructions>
    Actions:
    - "add": Add new clinical note (requires notes content)
    - "list": Show all patient notes (requires only patient_id)
    - "update": Modify existing note (requires record_id + notes content)
    - "delete": Remove note (requires record_id). Ask the user if they are sure they want to delete the note before proceeding.
    
    Use for: Important care instructions, provider alerts, patient preferences, social determinants
    Formal encounter notes should use documentEncounter() instead

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            match action:
                case "list":
                    response = await client.get(f"/patients/{patient_id}/quicknotes")
                    if response.get("quick_notes"):
                        note_count = len(response["quick_notes"])
                        response["guidance"] = f"Patient has {note_count} clinical notes. These are visible to all providers during patient care. Use action='add' for new important clinical information."
                    else:
                        response["guidance"] = "No clinical notes found. Use action='add' to document important patient information for provider awareness."
                    return response
                    
                case "add":
                    if not notes:
                        return {
                            "error": "Notes content required",
                            "guidance": "Provide the clinical note content. Use clear, professional language as this will be visible to all providers."
                        }
                    
                    response = await client.post(f"/patients/{patient_id}/quicknotes", data={"notes": notes})
                    if response.get("data"):
                        response["guidance"] = f"Clinical note added successfully. This important information is now visible to all providers during patient care. For detailed encounter documentation, use documentEncounter()."
                    return response
                    
                case "update":
                    if not record_id or not notes:
                        return {
                            "error": "record_id and notes content required for updates",
                            "guidance": "Use action='list' to find the note record_id, then provide the updated notes content."
                        }
                    
                    response = await client.put(f"patients/quicknotes/{record_id}", data={"notes": notes})
                    if response.get("code") == "0":
                        response["guidance"] = f"Clinical note {record_id} updated successfully. Updated information is now available to all providers."
                    return response
                    
                case "delete":
                    if not record_id:
                        return {
                            "error": "record_id required for deletion",
                            "guidance": "Use action='list' to find the note record_id first."
                        }
                    
                    response = await client.delete(f"patients/quicknotes/{record_id}")
                    if response.get("code") == "0":
                        response["guidance"] = f"Clinical note {record_id} deleted successfully. Information is no longer visible to providers."
                    return response
                    
        except Exception as e:
            logger.error(f"Error in managePatientNotes: {e}")
            return {
                "error": str(e),
                "guidance": f"Clinical note {action} failed. Consider documenting important patient information for provider awareness."
            }


@charm_mcp.tool
@with_tool_metrics()
async def managePatientRecalls(
    action: Literal["add", "list", "update", "delete"],
    patient_id: str,
    record_id: Optional[str] = None,
    
    # Recall fields
    recall_type: Optional[str] = None,
    provider_id: Optional[str] = None,
    facility_id: Optional[str] = None,
    recall_date: Optional[date] = None,
    recall_time: Optional[int] = None,
    recall_timeunit: Optional[str] = None,
    recall_period: Optional[str] = None,
    notes: Optional[str] = None,
    encounter_id: Optional[int] = None,
    
    # Reminder settings
    send_email_reminder: Optional[bool] = None,
    email_reminder_before: Optional[int] = None,
    send_text_reminder: Optional[bool] = None,
    text_reminder_before: Optional[int] = None,
) -> Dict[str, Any]:
    """
    <usecase>
    Patient recall and follow-up management - schedule preventive care reminders, follow-up appointments,
    and care plan reminders. Ensures patients receive timely care according to clinical guidelines.
    </usecase>
    
    <instructions>
    Actions:
    - "add": Schedule new recall (requires recall_type, notes, provider_id, facility_id)
    - "list": Show all patient recalls (requires only patient_id)
    - "update": Modify existing recall (requires record_id + fields to change)
    - "delete": Remove recall (requires record_id). Ask the user if they are sure they want to delete the recall before proceeding.
    
    Common recall types: "Annual Physical", "Mammogram", "Colonoscopy", "Lab Follow-up", "Medication Review"
    Reminder timing: email_reminder_before/text_reminder_before in days (e.g., 7 for one week)
    Use getPracticeInfo() to get valid provider_id and facility_id values

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            match action:
                case "list":
                    response = await client.get(f"/patients/{patient_id}/recalls")
                    if response.get("recall"):
                        recall_count = len(response["recall"])
                        active_recalls = [r for r in response["recall"] if r.get("status", "").lower() == "active"]
                        
                        guidance = f"Patient has {recall_count} total recalls, {len(active_recalls)} active"
                        guidance += ". These ensure timely preventive care and follow-up visits. Schedule appointments with managePatientAppointments() when recalls are due."
                        response["guidance"] = guidance
                    else:
                        response["guidance"] = "No recalls scheduled. Use action='add' to schedule preventive care reminders based on clinical guidelines and patient needs."
                    return response
                    
                case "add":
                    required = [recall_type, notes, provider_id, facility_id]
                    if not all(required):
                        return {
                            "error": "Missing required fields for recall",
                            "guidance": "For recalls, provide: recall_type, notes, provider_id, and facility_id. Use getPracticeInfo() to get valid provider and facility IDs."
                        }
                    
                    recall_data = [{
                        "recall_type": recall_type,
                        "notes": notes,
                        "provider_id": provider_id,
                        "facility_id": facility_id,
                        "recall_date": recall_date.isoformat() if recall_date else None,
                        "recall_time": recall_time,
                        "recall_timeunit": recall_timeunit,
                        "recall_period": recall_period,
                        "encounter_id": encounter_id,
                        "send_email_reminder": send_email_reminder,
                        "email_reminder_before": str(email_reminder_before) if email_reminder_before else None,
                        "send_text_reminder": send_text_reminder,
                        "text_reminder_before": str(text_reminder_before) if text_reminder_before else None
                    }]
                    
                    response = await client.post(f"/patients/{patient_id}/recalls", data=recall_data)
                    if response.get("recalls"):
                        reminder_info = ""
                        if send_email_reminder or send_text_reminder:
                            reminder_info = " Patient will receive automated reminders."
                        response["guidance"] = f"Recall for '{recall_type}' scheduled successfully.{reminder_info} Use managePatientAppointments() to schedule the actual appointment when due."
                    return response
                    
                case "update":
                    if not record_id:
                        return {
                            "error": "record_id required for updates",
                            "guidance": "Use action='list' to find the recall record_id first."
                        }
                    
                    update_data = {}
                    if recall_type:
                        update_data["recall_type"] = recall_type
                    if notes:
                        update_data["notes"] = notes
                    if recall_date:
                        update_data["recall_date"] = recall_date.isoformat()
                    if send_email_reminder is not None:
                        update_data["send_email_reminder"] = send_email_reminder
                    if send_text_reminder is not None:
                        update_data["send_text_reminder"] = send_text_reminder
                    
                    response = await client.put(f"/patients/{patient_id}/recalls/{record_id}", data=update_data)
                    if response.get("recalls"):
                        response["guidance"] = f"Recall {record_id} updated successfully. Updated reminder settings are now active."
                    return response
                    
                case "delete":
                    if not record_id:
                        return {
                            "error": "record_id required for deletion",
                            "guidance": "Use action='list' to find the recall record_id first."
                        }
                    
                    response = await client.delete(f"/patients/{patient_id}/recalls/{record_id}")
                    if response.get("code") == "0":
                        response["guidance"] = f"Recall {record_id} deleted successfully. Patient will no longer receive reminders for this recall."
                    return response
                    
        except Exception as e:
            logger.error(f"Error in managePatientRecalls: {e}")
            return {
                "error": str(e),
                "guidance": f"Recall {action} failed. Ensure patient_id is valid and provider/facility IDs exist. Use getPracticeInfo() to verify IDs."
            }

@charm_mcp.tool
@with_tool_metrics()
async def managePatientAppointments(
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
                        response["guidance"] = f"Appointment scheduled successfully (ID: {appt_id}). Use documentEncounter() after the visit to record clinical findings."
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
            logger.error(f"Error in managePatientAppointments: {e}")
            return {
                "error": str(e),
                "guidance": f"Appointment {action} failed. Check your parameters and try again. Use getPracticeInfo() to verify provider and facility IDs."
            }

@charm_mcp.tool
@with_tool_metrics()
async def managePatientFiles(
    action: Literal["upload_photo", "delete_photo", "upload_id", "send_phr_invite"],
    patient_id: str,
    # Photo fields
    photo_file: Optional[str] = None,
    
    # ID document fields  
    id_file: Optional[str] = None,
    id_qualifier: Optional[Literal["military_id", "state_issued_id", "unique_system_id", "permanent_resident_card", "passport_id", "drivers_license_id", "social_security_number", "tribal_id", "other"]] = None,
    id_of_patient: Optional[str] = None,
    
    # PHR invite fields
    email: Optional[str] = None,
    rep_first_name: Optional[str] = None,
    rep_last_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    <usecase>
    Patient file and document management - upload patient photos, manage identity documents, 
    and send PHR (Personal Health Record) invitations. Handles the complete patient file workflow.
    </usecase>
    
    <instructions>
    Actions:
    - "upload_photo": Upload patient photo (requires photo_file path)
    - "delete_photo": Remove patient photo (requires only patient_id)
    - "upload_id": Upload identity document (requires id_file, id_qualifier)
    - "send_phr_invite": Send PHR portal invitation (requires email)
    
    ID Qualifiers: military_id, state_issued_id, drivers_license_id, passport_id, social_security_number, etc.
    File paths should be absolute paths to image/PDF files on the system.

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            match action:
                case "upload_photo":
                    if not photo_file:
                        return {
                            "error": "photo_file path required",
                            "guidance": "Provide the file path to the patient photo to upload (JPG, PNG formats supported)."
                        }
                    
                    files = {"file": photo_file}
                    response = await client.post(f"/patients/{patient_id}/photo", files=files)
                    
                    if response.get("code") == "0":
                        response["guidance"] = "Patient photo uploaded successfully. The photo will now appear in the patient's profile for identification purposes."
                    else:
                        response["guidance"] = "Photo upload failed. Verify the file path exists and the file is a valid image format (JPG, PNG)."
                    
                    return response
                    
                case "delete_photo":
                    response = await client.delete(f"/patients/{patient_id}/photo")
                    
                    if response.get("code") == "0":
                        response["guidance"] = "Patient photo deleted successfully. The patient profile will no longer display a photo."
                    else:
                        response["guidance"] = "Photo deletion failed. Verify the patient has an existing photo to delete."
                    
                    return response
                    
                case "upload_id":
                    if not id_file or not id_qualifier:
                        return {
                            "error": "id_file and id_qualifier required",
                            "guidance": "Provide the file path to the ID document and specify the ID type (e.g., 'drivers_license_id', 'passport_id')."
                        }
                    
                    # Map qualifier to number
                    qualifier_map = {
                        "military_id": 1,
                        "state_issued_id": 2,
                        "unique_system_id": 3,
                        "permanent_resident_card": 4,
                        "passport_id": 5,
                        "drivers_license_id": 6,
                        "social_security_number": 7,
                        "tribal_id": 8,
                        "other": 99
                    }
                    
                    form_data = {
                        "id_qualifier": qualifier_map[id_qualifier]
                    }
                    
                    if id_of_patient:
                        form_data["id_of_patient"] = id_of_patient
                    
                    files = {"file": id_file}
                    
                    response = await client.post(f"/patients/{patient_id}/identity", data=form_data, files=files)
                    
                    if response.get("data"):
                        response["guidance"] = f"Identity document ({id_qualifier}) uploaded successfully. This document is now stored in the patient's secure file repository."
                    else:
                        response["guidance"] = "ID document upload failed. Verify the file path exists and the file is a valid image or PDF format."
                    
                    return response
                    
                case "send_phr_invite":
                    if not email:
                        return {
                            "error": "email required for PHR invitation",
                            "guidance": "Provide the patient's email address to send the PHR portal invitation."
                        }
                    
                    invite_data = {"email": email}
                    if rep_first_name:
                        invite_data["rep_first_name"] = rep_first_name
                    if rep_last_name:
                        invite_data["rep_last_name"] = rep_last_name
                    
                    response = await client.post(f"/patients/{patient_id}/invitations", data=invite_data)
                    
                    if response.get("code") == "0":
                        response["guidance"] = f"PHR invitation sent successfully to {email}. Patient will receive an email with instructions to access their personal health record portal."
                    else:
                        response["guidance"] = "PHR invitation failed. Verify the email address is valid and the patient doesn't already have an active PHR account."
                    
                    return response
                    
        except Exception as e:
            logger.error(f"Error in managePatientFiles: {e}")
            return {
                "error": str(e),
                "guidance": f"Patient file {action} failed. Check your file paths and parameters. Ensure files exist and are in supported formats."
            }

@charm_mcp.tool
@with_tool_metrics()
async def managePatientLabs(
    action: Literal["list", "get_details", "add_result"],
    # Common fields
    patient_id: Optional[str] = None,
    group_id: Optional[str] = None,
    lab_order_id: Optional[str] = None,
    
    # Listing fields
    reviewer_id: Optional[str] = None,
    status: Optional[int] = None,  # 0 or 2
    start_index: Optional[int] = None,
    no_of_records: Optional[int] = None,
    sort_by: Optional[Literal["DATE", "FULL_NAME"]] = None,
    is_ascending: Optional[bool] = None,
    
    # Adding lab results
    result_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    <usecase>
    Complete laboratory results management - list lab results, get detailed reports, 
    and add new lab results. Handles the full lab workflow for clinical decision-making.
    </usecase>
    
    <instructions>
    Actions:
    - "list": Show lab results with filtering (optionally filter by patient_id, reviewer_id, status)
    - "get_details": Get detailed lab report (requires group_id OR lab_order_id)
    - "add_result": Add new lab results (requires patient_id + result_details)
    
    For detailed results: Use group_id for result groups or lab_order_id for specific orders
    For adding results: Provide structured result_details with tests, parameters, and values
    Status codes: 0 for pending, 2 for final results

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    async with CharmHealthAPIClient() as client:
        try:
            match action:
                case "list":
                    params = {}
                    if reviewer_id:
                        params["reviewer_id"] = int(reviewer_id)
                    if patient_id:
                        params["patient_id"] = int(patient_id)
                    if status is not None:
                        params["status"] = status
                    if start_index:
                        params["start_index"] = start_index
                    if no_of_records:
                        params["no_of_records"] = no_of_records
                    if sort_by:
                        params["sort_by"] = sort_by
                    if is_ascending is not None:
                        params["is_ascending"] = is_ascending
                    
                    response = await client.get("/labs/results", params=params)
                    
                    if response.get("lab_results"):
                        result_count = len(response["lab_results"])
                        if patient_id:
                            response["guidance"] = f"Found {result_count} lab results for patient {patient_id}. If there is a group_id, use action='get_details' with group_id to see detailed results. Otherwise, use action='get_details' with lab_order_id to see detailed results."
                        else:
                            response["guidance"] = f"Found {result_count} lab results. Use action='get_details' to see specific result details or filter by patient_id."
                    else:
                        response["guidance"] = "No lab results found matching the criteria. Check your filter parameters or patient_id."
                    
                    return response
                    
                case "get_details":
                    if not group_id and not lab_order_id:
                        return {
                            "error": "Either group_id or lab_order_id required",
                            "guidance": "Provide group_id for result groups or lab_order_id for specific lab orders. Use action='list' to find these IDs."
                        }
                    
                    if group_id:
                        endpoint = f"/labs/results/{group_id}"
                    else:
                        endpoint = f"/labs/order/results/{lab_order_id}"
                    
                    response = await client.get(endpoint)
                    
                    if response.get("result_report"):
                        response["guidance"] = "Detailed lab results retrieved successfully. Review the test parameters and values for clinical interpretation."
                    else:
                        response["guidance"] = "Lab details not found. Verify the group_id or lab_order_id is correct using action='list' first."
                    
                    return response
                    
                case "add_result":
                    if not patient_id or not result_details:
                        return {
                            "error": "patient_id and result_details required",
                            "guidance": "Provide patient_id and structured result_details containing lab test information, parameters, and values."
                        }
                    
                    add_data = {
                        "patient_id": patient_id,
                        "result_details": result_details
                    }
                    
                    response = await client.post("/labs/results/upload", data=add_data)
                    
                    if response.get("code") == "0":
                        response["guidance"] = "Lab results added successfully. Results are now available in the patient's lab history and can be used for clinical decision-making."
                    else:
                        response["guidance"] = "Lab result upload failed. Verify the result_details structure includes required fields (tests, parameters, values) and patient_id is valid."
                    
                    return response
                    
        except Exception as e:
            logger.error(f"Error in managePatientLabs: {e}")
            return {
                "error": str(e),
                "guidance": f"Lab {action} failed. Check your parameters and ensure IDs are valid. Use action='list' to find correct group_id or lab_order_id values."
            } 
