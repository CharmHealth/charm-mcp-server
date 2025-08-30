from fastmcp import FastMCP
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

patient_management_mcp = FastMCP(name="CharmHealth Patient Management MCP Server")

@patient_management_mcp.tool
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
    Manage patients.

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
                        patient_data["mobile"] = phone.replace("-", "")
                    if home_phone:
                        patient_data["home_phone"] = home_phone.replace("-", "")
                    if work_phone:
                        patient_data["work_phone"] = work_phone.replace("-", "")
                    if work_phone_extn:
                        patient_data["work_phone_extn"] = work_phone_extn
                    if primary_phone:
                        patient_data["primary_phone"] = primary_phone.replace("-", "")
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

@patient_management_mcp.tool
@with_tool_metrics()
async def reviewPatientHistory(
    patient_id: str,
    include_demographics: bool = True,
    include_vitals: bool = True,
    include_medications: bool = True,
    include_allergies: bool = True,
    include_diagnoses: bool = True,
    include_encounters: bool = True,
    include_appointments: bool = True,
) -> Dict[str, Any]:
    """
    Review patient history.
    
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
            include_sections = [
                "demographics" if include_demographics else None,
                "vitals" if include_vitals else None,
                "medications" if include_medications else None,
                "allergies" if include_allergies else None,
                "diagnoses" if include_diagnoses else None,
                "encounters" if include_encounters else None,
                "appointments" if include_appointments else None
            ]
            include_sections = [section for section in include_sections if section is not None]
            
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
                    insights.append(f"Next appointment: {next_appt.get('appointment_date')} - use manageEncounter() after visit")
            
            patient_summary["clinical_insights"] = insights
            
            # Generate workflow-specific guidance
            workflow_guidance = []
            
            # Safety-first guidance
            if patient_summary.get("allergies"):
                workflow_guidance.append("Review allergies before prescribing with managePatientDrugs()")
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
                workflow_guidance.append(f"Next visit: {next_appt.get('appointment_date')} - prepare encounter with manageEncounter()()")
            else:
                workflow_guidance.append("No upcoming appointments - schedule follow-up with manageAppointments() if needed")
            
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
