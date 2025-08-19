from fastmcp import FastMCP
from typing import Optional, List, Dict, Any
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals
import logging
from telemetry import telemetry, with_tool_metrics

if telemetry:
    telemetry.initialize()

logger = logging.getLogger(__name__)

patient_management_mcp = FastMCP(name="Patient Management")

def build_patient_payload(locals_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the patient API payload from function parameters
    """
    exclude = ["patient_id"]
    params = {}

    address_fields = {}
    address_params = [
        "address_line1", "address_line2", "area", "city", "state", 
        "county_code", "country", "zip_code", "post_box", "district"
    ]
    for param in address_params:
        if param in locals_dict and locals_dict[param] is not None:
            address_fields[param] = locals_dict[param]
    
    if address_fields:
        params["address"] = address_fields

    for k, v in locals_dict.items():
        if k not in exclude and v is not None:
            if isinstance(v, date):
                params[k] = v.isoformat()
            elif isinstance(v, bool):
                params[k] = str(v).lower()
            else:
                params[k] = v
    return params


@patient_management_mcp.tool
@with_tool_metrics()
async def list_patients(
    facility_id: str = "ALL",
    full_name_startswith: Optional[str] = None,
    full_name_contains: Optional[str] = None,
    full_name: Optional[str] = None,
    first_name_startswith: Optional[str] = None,
    first_name_contains: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name_startswith: Optional[str] = None,
    last_name_contains: Optional[str] = None,
    last_name: Optional[str] = None,
    record_id_startswith: Optional[str] = None,
    record_id_contains: Optional[str] = None,
    record_id: Optional[str] = None,
    category_id: Optional[int] = None,
    gender: Optional[str] = None,
    dob: Optional[date] = None,
    email_startswith: Optional[str] = None,
    email_contains: Optional[str] = None,
    email: Optional[str] = None,
    mobile_startswith: Optional[str] = None,
    mobile_contains: Optional[str] = None,
    mobile: Optional[str] = None,
    home_phone_startswith: Optional[str] = None,
    home_phone_contains: Optional[str] = None,
    home_phone: Optional[str] = None,
    work_phone_startswith: Optional[str] = None,
    work_phone_contains: Optional[str] = None,
    work_phone: Optional[str] = None,
    created_date_start: Optional[date] = None,
    created_date_end: Optional[date] = None,
    filter_by: Optional[str] = None,
    modified_time_greater_than: Optional[int] = None,
    modified_time_less_than: Optional[int] = None,
    modified_time_greater_equals: Optional[int] = None,
    modified_time_less_equals: Optional[int] = None,
    is_phr_account_available: Optional[bool] = None,
    gender_identity: Optional[str] = None,
    state: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    postal_code: Optional[str] = None,
    county: Optional[str] = None,
    district: Optional[str] = None,
    age_greater_equals: Optional[int] = None,
    age_lesser_equals: Optional[int] = None,
    patient_ids: Optional[str] = None,
    blood_group: Optional[str] = None,
    language: Optional[str] = None,
    marital_status: Optional[str] = None,
    source: Optional[str] = None,
    category: Optional[str] = None,
    sort_order: Optional[str] = None,
    sort_column: Optional[str] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Fetch the patients from the practice with various filtering and search options.
    """
    async with CharmHealthAPIClient() as client:
        try:
            params = build_params_from_locals(locals())
            response = await client.get("/patients", params=params)
            logger.info(f"Tool call completed for list_patients, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in list_patients: {e}")
            return {"error": str(e)}


@patient_management_mcp.tool
@with_tool_metrics()
async def get_patient_details(
    patient_id: str,
) -> Dict[str, Any]:
    """
    Get the details of a patient from CharmHealth API.
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.get(f"/patients/{patient_id}")
            logger.info(f"Tool call completed for get_patient_details, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in get_patient_details: {e}")
            return {"error": str(e)}


@patient_management_mcp.tool
@with_tool_metrics()
async def add_patient(
    first_name: str,  # max-length is 35
    last_name: str,   # max-length is 35
    gender: str,      # Allowed Values: male, female, unknown, other
    facilities: List[Dict[str, Any]],  # Required - [{"facility_id": Long}]
    dob: Optional[date] = None,  # Required if age is not given, format: yyyy-mm-dd
    age: Optional[int] = None,   # Required if dob is not given
    middle_name: Optional[str] = None,  # max-length is 35
    record_id: Optional[str] = None,    # max-length is 20
    gender_identity: Optional[str] = None,  # max-length is 100
    nick_name: Optional[str] = None,    # max-length is 35
    suffix: Optional[str] = None,       # max-length is 20
    maiden_name: Optional[str] = None,  # max-length is 35
    deceased: Optional[bool] = None,
    dod: Optional[date] = None,         # Date of death if deceased, format: yyyy-mm-dd
    cause_of_death: Optional[str] = None,  # max-length is 35
    linked_patient_id: Optional[int] = None,  # Long
    id_qualifiers: Optional[List[Dict[str, Any]]] = None,  # [{"id_qualifier": int, "id_of_patient": str}]
    
    # Address fields (Table 3)
    address_line1: Optional[str] = None,    # max-length is 35
    address_line2: Optional[str] = None,    # max-length is 35
    area: Optional[str] = None,             # max-length is 100
    city: Optional[str] = None,             # max-length is 35
    state: Optional[str] = None,            # max-length is 50 (Pass entire State value. Ex: "New Jersey")
    county_code: Optional[str] = None,      # max-length is 20
    country: Optional[str] = None,          # max-length is 2, Required if any address field is provided
    zip_code: Optional[str] = None,         # max-length is 10
    post_box: Optional[int] = None,         # max-length is 4
    district: Optional[str] = None,         # max-length is 50
    
    # Contact fields
    mobile: Optional[str] = None,           # max-length is 15
    home_phone: Optional[str] = None,       # max-length is 15
    work_phone: Optional[str] = None,       # max-length is 15
    work_phone_extn: Optional[str] = None,  # max-length is 4
    email: Optional[str] = None,            # max-length is 100
    primary_phone: Optional[str] = None,    # Allowed Values: Home Phone, Mobile Phone, Work Phone
    
    # Emergency contact
    emergency_contact_name: Optional[str] = None,   # max-length is 70
    emergency_contact_number: Optional[str] = None, # max-length is 10
    emergency_extn: Optional[str] = None,           # max-length is 4
    
    # Complex nested objects (keeping as structured for now due to array complexity)
    caregivers: Optional[List[Dict[str, Any]]] = None,  # Table 4 structure
    guarantor: Optional[List[Dict[str, Any]]] = None,   # Table 5 structure
    
    # Communication preferences
    preferred_communication: Optional[str] = None,  # Allowed Values: ChARM PHR, Email, Phone, Fax, Mail
    email_notification: Optional[bool] = None,
    text_notification: Optional[bool] = None,
    voice_notification: Optional[bool] = None,
    
    # Medical information
    blood_group: Optional[str] = None,  # Allowed Values: unknown, B+, B-, O+, O-, A+, A-, A1+, A1-, A2+, A2-, AB+, AB-, A1B+, A1B-, A2B+, A2B-
    language: Optional[str] = None,     # max-length is 100
    race: Optional[str] = None,
    ethnicity: Optional[str] = None,
    smoking_status: Optional[str] = None,  # Allowed Values: Current every day smoker, Current some day smoker, Former Smoker, Never Smoker, Smoker current status unknown, Unknown if ever smoked, Heavy tobacco smoker, Light tobacco smoker
    marital_status: Optional[str] = None,  # Allowed Values: Single, Married, Other
    employment_status: Optional[str] = None,  # Allowed Values: Employed, Full-Time Student, Part-Time Student, Unemployed, Retired
    sexual_orientation: Optional[str] = None,  # max-length is 250
    
    # Family information
    mother_first_name: Optional[str] = None,  # max-length is 35
    mother_last_name: Optional[str] = None,   # max-length is 35
    is_multiple_birth: Optional[bool] = None,
    birth_order: Optional[int] = None,
    
    # Categories and custom fields
    categories: Optional[List[Dict[str, Any]]] = None,  # [{"category_id": Long}]
    introduction: Optional[str] = None,     # max-length is 600
    custom_field_1: Optional[str] = None,   # max-length is 250
    custom_field_2: Optional[str] = None,   # max-length is 250
    custom_field_3: Optional[str] = None,   # max-length is 250
    custom_field_4: Optional[str] = None,   # max-length is 250
    custom_field_5: Optional[str] = None,   # max-length is 250
    
    # Source and payment information
    source_name: Optional[str] = None,      # max-length is 100
    source_value: Optional[str] = None,     # max-length is 100
    payment_source: Optional[str] = None,   # max-length is 200
    payment_start_date: Optional[date] = None,  # format: yyyy-mm-dd
    payment_end_date: Optional[date] = None,    # format: yyyy-mm-dd
    
    # Representative information
    rep_first_name: Optional[str] = None,   # max-length is 35
    rep_last_name: Optional[str] = None,    # max-length is 35
    
    # Control flags
    send_phr_invite: Optional[bool] = False,
    duplicate_check: Optional[bool] = True,
) -> Dict[str, Any]:
    """
    Add a new patient to CharmHealth.
    
    Required parameters:
    - first_name, last_name, gender, facilities
    - Either dob or age must be provided
    - If any address field is provided, country is required
    
    facilities format: [{"facility_id": <facility_id>}]
    id_qualifiers format: [{"id_qualifier": <qualifier_number>, "id_of_patient": "<id_value>"}]
    categories format: [{"category_id": <category_id>}]
    
    caregivers format: [{
        "first_name": str, "last_name": str, "relationship": str,
        "middle_name": str (optional), "dob": "yyyy-mm-dd" (optional),
        "gender": str (optional), "ssn": str (optional),
        "same_as_patient_contact": bool (optional),
        "contact": {"mobile": str, "home_phone": str, "work_phone": str, "work_phone_extn": str, "email": str},
        "address": {"address_line1": str, "city": str, "state": str, "country": str, ...}
    }]
    
    guarantor format: [{
        "first_name": str, "last_name": str, "relationship": str,
        "middle_name": str (optional), "dob": "yyyy-mm-dd" (optional),
        "gender": str (optional), "ssn": str (optional),
        "contact": {"mobile": str, "home_phone": str, "work_phone": str, "work_phone_extn": str, "email": str},
        "address": {"address_line1": str, "city": str, "state": str, "country": str, ...}
    }]
    """
    async with CharmHealthAPIClient() as client:
        try:
            params = build_patient_payload(locals())
            response = await client.post("/patients", data=params)
            logger.info(f"Tool call completed for add_patient, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_patient: {e}")
            return {"error": str(e)}


@patient_management_mcp.tool
@with_tool_metrics()
async def update_patient(
    patient_id: str,
    first_name: str,  # max-length is 35
    last_name: str,   # max-length is 35
    gender: str,      # Allowed Values: male, female, unknown, other
    facilities: List[Dict[str, Any]],  # Required - [{"facility_id": Long}]
    record_id: str,   # Required for update patient API, max-length is 20
    dob: Optional[date] = None,  # Required if age is not given, format: yyyy-mm-dd
    age: Optional[int] = None,   # Required if dob is not given
    middle_name: Optional[str] = None,  # max-length is 35
    gender_identity: Optional[str] = None,  # max-length is 100
    nick_name: Optional[str] = None,    # max-length is 35
    suffix: Optional[str] = None,       # max-length is 20
    maiden_name: Optional[str] = None,  # max-length is 35
    deceased: Optional[bool] = None,
    dod: Optional[date] = None,         # Date of death if deceased, format: yyyy-mm-dd
    cause_of_death: Optional[str] = None,  # max-length is 35
    linked_patient_id: Optional[int] = None,  # Long
    id_qualifiers: Optional[List[Dict[str, Any]]] = None,  # [{"id_qualifier": int, "id_of_patient": str}]
    
    # Address fields (Table 3)
    address_line1: Optional[str] = None,    # max-length is 35
    address_line2: Optional[str] = None,    # max-length is 35
    area: Optional[str] = None,             # max-length is 100
    city: Optional[str] = None,             # max-length is 35
    state: Optional[str] = None,            # max-length is 50 (Pass entire State value. Ex: "New Jersey")
    county_code: Optional[str] = None,      # max-length is 20
    country: Optional[str] = None,          # max-length is 2, Required if any address field is provided
    zip_code: Optional[str] = None,         # max-length is 10
    post_box: Optional[int] = None,         # max-length is 4
    district: Optional[str] = None,         # max-length is 50
    
    # Contact fields
    mobile: Optional[str] = None,           # max-length is 15
    home_phone: Optional[str] = None,       # max-length is 15
    work_phone: Optional[str] = None,       # max-length is 15
    work_phone_extn: Optional[str] = None,  # max-length is 4
    email: Optional[str] = None,            # max-length is 100
    primary_phone: Optional[str] = None,    # Allowed Values: Home Phone, Mobile Phone, Work Phone
    
    # Emergency contact
    emergency_contact_name: Optional[str] = None,   # max-length is 70
    emergency_contact_number: Optional[str] = None, # max-length is 10
    emergency_extn: Optional[str] = None,           # max-length is 4
    
    # Complex nested objects (keeping as structured for now due to array complexity)
    caregivers: Optional[List[Dict[str, Any]]] = None,  # Table 4 structure
    guarantor: Optional[List[Dict[str, Any]]] = None,   # Table 5 structure
    
    # Communication preferences
    preferred_communication: Optional[str] = None,  # Allowed Values: ChARM PHR, Email, Phone, Fax, Mail
    email_notification: Optional[bool] = None,
    text_notification: Optional[bool] = None,
    voice_notification: Optional[bool] = None,
    
    # Medical information
    blood_group: Optional[str] = None,  # Allowed Values: unknown, B+, B-, O+, O-, A+, A-, A1+, A1-, A2+, A2-, AB+, AB-, A1B+, A1B-, A2B+, A2B-
    language: Optional[str] = None,     # max-length is 100
    race: Optional[str] = None,
    ethnicity: Optional[str] = None,
    smoking_status: Optional[str] = None,  # Allowed Values: Current every day smoker, Current some day smoker, Former Smoker, Never Smoker, Smoker current status unknown, Unknown if ever smoked, Heavy tobacco smoker, Light tobacco smoker
    marital_status: Optional[str] = None,  # Allowed Values: Single, Married, Other
    employment_status: Optional[str] = None,  # Allowed Values: Employed, Full-Time Student, Part-Time Student, Unemployed, Retired
    sexual_orientation: Optional[str] = None,  # max-length is 250
    
    # Family information
    mother_first_name: Optional[str] = None,  # max-length is 35
    mother_last_name: Optional[str] = None,   # max-length is 35
    is_multiple_birth: Optional[bool] = None,
    birth_order: Optional[int] = None,
    
    # Categories and custom fields
    categories: Optional[List[Dict[str, Any]]] = None,  # [{"category_id": Long}]
    introduction: Optional[str] = None,     # max-length is 600
    custom_field_1: Optional[str] = None,   # max-length is 250
    custom_field_2: Optional[str] = None,   # max-length is 250
    custom_field_3: Optional[str] = None,   # max-length is 250
    custom_field_4: Optional[str] = None,   # max-length is 250
    custom_field_5: Optional[str] = None,   # max-length is 250
    
    # Source and payment information
    source_name: Optional[str] = None,      # max-length is 100
    source_value: Optional[str] = None,     # max-length is 100
    payment_source: Optional[str] = None,   # max-length is 200
    payment_start_date: Optional[date] = None,  # format: yyyy-mm-dd
    payment_end_date: Optional[date] = None,    # format: yyyy-mm-dd
    
    # Representative information
    rep_first_name: Optional[str] = None,   # max-length is 35
    rep_last_name: Optional[str] = None,    # max-length is 35
    
    # Control flags
    send_phr_invite: Optional[bool] = False,
    duplicate_check: Optional[bool] = True,
    update_specific_details: Optional[bool] = None,  # Update only the values sent in the request
) -> Dict[str, Any]:
    """
    Update an existing patient in CharmHealth.
    
    Required parameters:
    - patient_id, first_name, last_name, gender, facilities, record_id
    - Either dob or age must be provided
    - If any address field is provided, country is required
    
    See add_patient for detailed format specifications for complex objects.
    """
    async with CharmHealthAPIClient() as client:
        try:
            params = build_patient_payload(locals())
            response = await client.put(f"/patients/{patient_id}", data=params)
            logger.info(f"Tool call completed for update_patient, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in update_patient: {e}")
            return {"error": str(e)}
    

@patient_management_mcp.tool
@with_tool_metrics()
async def deactivate_patient(
    patient_id: str,
) -> Dict[str, Any]:
    """
    Deactivate a patient in CharmHealth.
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.post(f"/patients/{patient_id}/inactive")
            logger.info(f"Tool call completed for deactivate_patient, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in deactivate_patient: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def activate_patient(
    patient_id: str,
) -> Dict[str, Any]:
    """
    Activate a patient in CharmHealth.
    
    This function reactivates a previously deactivated patient, making them active
    in the system again. The patient will be able to receive care and their
    information will be accessible for scheduling and medical records.
    
    Args:
        patient_id (str): The unique identifier for the patient to activate
        
    Returns:
        Dict[str, Any]: Response from the CharmHealth API containing:
            - Success confirmation or error details
            - Patient activation status
            - Any relevant messages from the API
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.post(f"/patients/{patient_id}/active")
            logger.info(f"Tool call completed for activate_patient, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in activate_patient: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def send_phr_invite(
    patient_id: str,
    email: str,
    rep_first_name: Optional[str] = None,
    rep_last_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send a PHR invite to a patient in CharmHealth.

    This function sends a PHR invite to a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to send the invite to
        email (str): The email address of the patient to send the invite to
        rep_first_name (Optional[str]): The first name of the representative sending the invite
    """
    async with CharmHealthAPIClient() as client:
        try:
            data = {
                "email": email,
                "rep_first_name": rep_first_name,
                "rep_last_name": rep_last_name
            }
            response = await client.post(f"/patients/{patient_id}/invitations", data=data)
            logger.info(f"Tool call completed for send_phr_invite, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in send_phr_invite: {e}")
            return {"error": str(e)}
    
@patient_management_mcp.tool
@with_tool_metrics()
async def upload_patient_id(
    patient_id: str,
    id_qualifier: str,  # Required - ID Qualifier, will be one of the following: military_id, state_issued_id, unique_system_id, permanent_resident_card, passport_id, drivers_license_id, social_security_number, tribal_id, other. If not one of the above, use "other"
    file: str,  # Required - Path to identity file (image/pdf)
    id_of_patient: Optional[str] = None,  # Optional - id of patient
) -> Dict[str, Any]:
    """
    Upload a patient identity document to CharmHealth.
    
    ID Qualifier Numbers:
    1 - Military ID
    2 - State Issued ID
    3 - Unique System ID
    4 - Permanent Resident Card (Green Card)
    5 - Passport ID
    6 - Driver's License ID
    7 - Social Security Number
    8 - Tribal ID
    99 - Other
    
    Args:
        patient_id: The ID of the patient
        id_qualifier: ID Qualifier Number (1-8, 99)
        file: Path to the identity file (image/pdf format)
        id_of_patient: Optional ID of patient
    """
    async with CharmHealthAPIClient() as client:
        try:
            match id_qualifier:
                case "military_id":
                    id_qualifier = 1
                case "state_issued_id":
                    id_qualifier = 2
                case "unique_system_id":
                    id_qualifier = 3
                case "permanent_resident_card":
                    id_qualifier = 4
                case "passport_id":
                    id_qualifier = 5
                case "drivers_license_id":
                    id_qualifier = 6
                case "social_security_number":
                    id_qualifier = 7
                case "tribal_id":
                    id_qualifier = 8
                case "other":
                    id_qualifier = 99
                case _:
                    raise ValueError(f"Invalid ID Qualifier: {id_qualifier}")
            form_data = {
                "id_qualifier": id_qualifier,
            }
            
            if id_of_patient is not None:
                form_data["id_of_patient"] = id_of_patient
            
            # Handle file upload
            files = {"file": file}
            
            response = await client.post(f"/patients/{patient_id}/identity", data=form_data, files=files)
            logger.info(f"Tool call completed for upload_patient_id, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in upload_patient_id: {e}")
            return {"error": str(e)}
    

@patient_management_mcp.tool
@with_tool_metrics()
async def upload_patient_photo(
    patient_id: str,
    file: str,
) -> Dict[str, Any]:
    """
    Upload a patient photo to CharmHealth.

    This function uploads a photo of a patient to CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to upload the photo for
        file (str): The path to the photo file to upload
        
    """
    async with CharmHealthAPIClient() as client:
        try:
            files = {"file": file}
            response = await client.post(f"/patients/{patient_id}/photo", files=files)
            logger.info(f"Tool call completed for upload_patient_photo, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in upload_patient_photo: {e}")
            return {"error": str(e)}
    
@patient_management_mcp.tool
@with_tool_metrics()
async def delete_patient_photo(
    patient_id: str,
) -> Dict[str, Any]:
    """
    Delete a patient photo from CharmHealth.

    This function deletes a photo of a patient from CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to delete the photo for
        
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.delete(f"/patients/{patient_id}/photo")
            logger.info(f"Tool call completed for delete_patient_photo, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in delete_patient_photo: {e}")
            return {"error": str(e)}


# =========================== PATIENT QUICK NOTES ===========================
@patient_management_mcp.tool
@with_tool_metrics()
async def list_quick_notes(
    patient_id: str,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    sort_order: Optional[str] = None,
) -> Dict[str, Any]:
    """
    List quick notes for a patient in CharmHealth.

    This function lists all quick notes for a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to list quick notes for
        page (Optional[int]): The page number to return
    """
    async with CharmHealthAPIClient() as client:
        try:
            endpoint = f"/patients/{patient_id}/quicknotes"
            params = {}
            if page:
                params["page"] = page
            if per_page:
                params["per_page"] = per_page
            if sort_order:
                params["sort_order"] = sort_order
            response = await client.get(endpoint, params=params)
            logger.info(f"Tool call completed for list_quick_notes, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in list_quick_notes: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def add_quick_note(
    patient_id: str,
    notes: str,
) -> Dict[str, Any]:
    """
    Add a quick note to a patient in CharmHealth.

    This function adds a quick note to a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to add the quick note to
        notes (str): The notes to add to the patient
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.post(f"/patients/{patient_id}/quicknotes", data={"notes": notes})
            logger.info(f"Tool call completed for add_quick_note, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_quick_note: {e}")
            return {"error": str(e)}


@patient_management_mcp.tool
@with_tool_metrics()
async def edit_quick_note(
    quick_note_id: str,
    notes: str,
) -> Dict[str, Any]:
    """
    Edit a quick note in CharmHealth.

    This function edits a quick note in CharmHealth.
    
    Args:
        quick_note_id (str): The unique identifier for the quick note to edit
        notes (str): The notes to edit the quick note to
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.put(f"patients/quicknotes/{quick_note_id}", data={"notes": notes})
            logger.info(f"Tool call completed for edit_quick_note, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in edit_quick_note: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def delete_quick_note(
    quick_note_id: str,
) -> Dict[str, Any]:
    """
    Delete a quick note in CharmHealth.

    This function deletes a quick note in CharmHealth.
    
    Args:
        quick_note_id (str): The unique identifier for the quick note to delete
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.delete(f"patients/quicknotes/{quick_note_id}")
            logger.info(f"Tool call completed for delete_quick_note, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in delete_quick_note: {e}")
            return {"error": str(e)}


# =========================== PATIENT RECALLS ===========================
@patient_management_mcp.tool
@with_tool_metrics()
async def get_recalls(
    patient_id: str,
) -> Dict[str, Any]:
    """
    Get recalls for a patient in CharmHealth. 

    This function gets all recalls for a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to get recalls for
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.get(f"/patients/{patient_id}/recalls")
            logger.info(f"Tool call completed for get_recalls, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in get_recalls: {e}")
            return {"error": str(e)}
    

@patient_management_mcp.tool
@with_tool_metrics()
async def add_recall(
    patient_id: str,
    recall_type: str,  # Required - Recall types
    notes: str,  # Required - Notes about the recall
    provider_id: str,  # Required - Provider Identifier
    facility_id: str,  # Required - Facility Identifier
    recall_date: Optional[date] = None,  # Optional - Due date of the recall (YYYY-MM-DD)
    recall_time: Optional[int] = None,  # Optional - to calculate due date from this
    recall_timeunit: Optional[str] = None,  # Optional - days/weeks/months
    recall_period: Optional[str] = None,  # Optional - after/in/on
    encounter_id: Optional[int] = None,  # Optional - Recall mapped to consultation
    send_email_reminder: Optional[bool] = None,  # Optional - If true, email reminder will go
    email_reminder_before: Optional[int] = None,  # Optional - No of days before due date to send email reminder
    send_text_reminder: Optional[bool] = None,  # Optional - If true, text reminder will go
    text_reminder_before: Optional[int] = None,  # Optional - No of days before due date to send text reminder
    send_voice_reminder: Optional[bool] = None,  # Optional - If true, voice reminder will go
    voice_reminder_before: Optional[int] = None,  # Optional - No of days before due date to send voice reminder
) -> Dict[str, Any]:
    """
    Add a recall to a patient in CharmHealth.
    
    Note: Either recall_date OR (recall_time + recall_timeunit + recall_period) should be provided.
    
    Args:
        patient_id: Patient identifier
        recall_type: Recall types (required)
        notes: Notes about the recall (required)
        provider_id: Provider Identifier (required)
        facility_id: Facility Identifier (required)
        recall_date: Due date of the recall (YYYY-MM-DD format)
        recall_time: Integer to calculate due date from this
        recall_timeunit: Time unit - days/weeks/months
        recall_period: Recall period - after/in/on
        encounter_id: Recall mapped to consultation
        send_email_reminder: If true, email reminder will go
        email_reminder_before: No of days before due date to send email reminder
        send_text_reminder: If true, text reminder will go
        text_reminder_before: No of days before due date to send text reminder
        send_voice_reminder: If true, voice reminder will go
        voice_reminder_before: No of days before due date to send voice reminder
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Use build_params_from_locals to build the recall data
            recall_data = build_params_from_locals(locals())
            
            # Convert integer fields to strings as required by API
            string_fields = ["email_reminder_before", "text_reminder_before", "voice_reminder_before"]
            for field in string_fields:
                if field in recall_data and recall_data[field] is not None:
                    recall_data[field] = str(recall_data[field])
            
            # API expects a JSONArray, so wrap in array
            data = [recall_data]
            
            response = await client.post(f"/patients/{patient_id}/recalls", data=data)
            logger.info(f"Tool call completed for add_recall, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_recall: {e}")
            return {"error": str(e)}
    

# =========================== PATIENT SUPPLEMENTS ===========================
@patient_management_mcp.tool
@with_tool_metrics()
async def add_supplement(
    patient_id: str,
    supplement_name: str,  # Required - Supplement name
    dosage: int,  # Required - Dosage of Supplements
    strength: Optional[str] = None,  # Optional - Strength of supplement
    supplement_type: Optional[str] = None,  # Optional - Manufactured | Compounded
    status: Optional[str] = None,  # Optional - Active | Inactive
    start_date: Optional[date] = None,  # Optional - Start Date (YYYY-MM-DD)
    end_date: Optional[date] = None,  # Optional - Stop date (YYYY-MM-DD)
    encounter_id: Optional[int] = None,  # Optional - Map with encounter
    frequency: Optional[str] = None,  # Optional - Frequency (Once, Once a day, etc.)
    intake_type: Optional[str] = None,  # Optional - Before Meals, After Meals, etc.
    refills: Optional[int] = None,  # Optional - Refills to use Supplements
    weaning_schedule: Optional[str] = None,  # Optional - Weaning schedule
    route: Optional[str] = None,  # Optional - Oral, Rectal, Topical, etc.
    dose_form: Optional[str] = None,  # Optional - Dose form of supplement
    dosage_unit: Optional[str] = None,  # Optional - Dosage unit of supplement
    comments: Optional[str] = None,  # Optional - Comment about supplement
    quantity: Optional[int] = None,  # Optional - Dispense quantity
) -> Dict[str, Any]:
    """
    Add supplements for a patient in CharmHealth.
    
    Required parameters:
    - supplement_name: Supplement name
    - dosage: Dosage of supplements (integer)
    
    Optional parameters include:
    - supplement_type: "Manufactured" or "Compounded"
    - status: "Active" or "Inactive"
    - frequency: "Once", "Once a day", "Twice a day", "3 times a day", etc.
    - intake_type: "Before Meals", "After Meals", "At Bedtime", "With Meals", etc.
    - route: "Oral", "Rectal", "Topical", "Nasal", "Vaginal", "Inhaled", etc.
    - dates, encounter mapping, dosage details, etc.
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Use build_params_from_locals to build the supplement data
            supplement_data = build_params_from_locals(locals())
            supplement_data.pop("patient_id")
            
            # API expects a JSONArray, so wrap in array
            data = [supplement_data]
            
            response = await client.post(f"/patients/{patient_id}/supplements", data=data)
            logger.info(f"Tool call completed for add_supplement, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_supplement: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def list_supplements(
    patient_id: str,
    encounter_id: Optional[str] = None,
    sort_order: Optional[str] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
) -> Dict[str, Any]:
    """
    List supplements for a patient in CharmHealth.

    This function lists all supplements for a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to list supplements for
        encounter_id (Optional[str]): The unique identifier for the encounter to list supplements for
        sort_order (Optional[str]): The order to sort the supplements in
    """
    async with CharmHealthAPIClient() as client:
        try:
            endpoint = f"/patients/{patient_id}/supplements"
            params = {}
            if encounter_id:
                params["encounter_id"] = encounter_id
            if page:
                params["page"] = page
            if per_page:
                params["per_page"] = per_page
            if sort_order:
                params["sort_order"] = sort_order
            response = await client.get(endpoint, params=params)
            logger.info(f"Tool call completed for list_supplements, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in list_supplements: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def edit_supplement(
    patient_id: str,
    supplement_id: str,
    supplement_name: str,  # Required - Supplement name
    dosage: int,  # Required - Dosage of Supplements
    strength: Optional[str] = None,  # Optional - Strength of supplement
    supplement_type: Optional[str] = None,  # Optional - Manufactured | Compounded
    status: Optional[str] = None,  # Optional - Active | Inactive
    start_date: Optional[date] = None,  # Optional - Start Date (YYYY-MM-DD)
    end_date: Optional[date] = None,  # Optional - Stop date (YYYY-MM-DD)
    encounter_id: Optional[int] = None,  # Optional - Map with encounter
    frequency: Optional[str] = None,  # Optional - Frequency (Once, Once a day, etc.)
    intake_type: Optional[str] = None,  # Optional - Before Meals, After Meals, etc.
    refills: Optional[int] = None,  # Optional - Refills to use Supplements
    weaning_schedule: Optional[str] = None,  # Optional - Weaning schedule
    route: Optional[str] = None,  # Optional - Oral, Rectal, Topical, etc.
    dose_form: Optional[str] = None,  # Optional - Dose form of supplement
    dosage_unit: Optional[str] = None,  # Optional - Dosage unit of supplement
    comments: Optional[str] = None,  # Optional - Comment about supplement
    quantity: Optional[int] = None,  # Optional - Dispense quantity
) -> Dict[str, Any]:
    """
    Edit a supplement in CharmHealth.

    This function edits a supplement in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to edit the supplement for
        supplement_id (str): The unique identifier for the supplement to edit
        supplement_name (str): The name of the supplement to edit
    """
    async with CharmHealthAPIClient() as client:
        try:
            data = build_params_from_locals(locals())
            data.pop("patient_id")
            response = await client.put(f"/patients/{patient_id}/supplements/{supplement_id}", data=data)
            logger.info(f"Tool call completed for edit_supplement, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in edit_supplement: {e}")
            return {"error": str(e)}
    

# =========================== PATIENT ALLERGIES ===========================
@patient_management_mcp.tool
@with_tool_metrics()
async def add_allergy(
    patient_id: str,
    allergen: str,
    type: str,
    severity:str,
    status:str,
    reactions:str,
    date:date
) -> Dict[str, Any]:
    """
    Add an allergy to a patient in CharmHealth.

    This function adds an allergy to a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to add the allergy to
        allergen (str): The allergen to add to the patient
    """
    async with CharmHealthAPIClient() as client:
        try:
            data = build_params_from_locals(locals())
            data.pop("patient_id")
            response = await client.post(f"/patients/{patient_id}/allergies", data=data)
            logger.info(f"Tool call completed for add_allergy, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_allergy: {e}")
            return {"error": str(e)}
    
@patient_management_mcp.tool
@with_tool_metrics()
async def get_allergies(
    patient_id: str,
) -> Dict[str, Any]:
    """
    Get allergies for a patient in CharmHealth.

    This function gets all allergies for a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to get allergies for
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.get(f"/patients/{patient_id}/allergies")
            logger.info(f"Tool call completed for get_allergies, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in get_allergies: {e}")
            return {"error": str(e)}
    

@patient_management_mcp.tool
@with_tool_metrics()
async def edit_allergy(
    patient_id: str,
    allergy_id: str,
    allergen: Optional[str] = None,
    type: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    reactions: Optional[str] = None,
    date: Optional[date] = None,
) -> Dict[str, Any]:
    """
    Edit a patient's allergy in CharmHealth.

    This function edits a patient's allergy in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to edit the allergy for
        allergy_id (str): The unique identifier for the allergy to edit
    """
    async with CharmHealthAPIClient() as client:
        try:
            data = build_params_from_locals(locals())
            data.pop("patient_id")
            response = await client.put(f"/patients/{patient_id}/allergies/{allergy_id}", data=data)
            logger.info(f"Tool call completed for edit_allergy, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in edit_allergy: {e}")
            return {"error": str(e)}
    
@patient_management_mcp.tool
@with_tool_metrics()
async def delete_allergy(
    patient_id: str,
    allergy_id: str,
) -> Dict[str, Any]:
    """
    Delete a patient's allergy in CharmHealth.

    This function deletes a patient's allergy in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to delete the allergy for
        allergy_id (str): The unique identifier for the allergy to delete
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.delete(f"/patients/{patient_id}/allergies/{allergy_id}")
            logger.info(f"Tool call completed for delete_allergy, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in delete_allergy: {e}")
            return {"error": str(e)}
# =========================== PATIENT MEDICATIONS ===========================
@patient_management_mcp.tool
@with_tool_metrics()
async def add_medication(
    patient_id: str,
    drug_name: str,  # Required - Drug name
    is_active: bool,  # Required - Medication status
    directions: str,  # Required - Directions to use medication
    dispense: float,  # Required - Dispense of medication
    refills: str,  # Required - Refills ([0-9]{1,2} | PRN | -1)
    substitute_generic: bool,  # Required - Other brands are allowed for that drug
    manufacturing_type: str,  # Required - Manufactured | Compounded
    trade_name: Optional[str] = None,  # Optional - Trade name of drug
    strength_description: Optional[str] = None,  # Optional - Strength of drug
    is_custom_drug: Optional[bool] = False,  # Optional - Default value false
    is_directions_edited: Optional[bool] = False,  # Optional - Default value false
    start_date: Optional[date] = None,  # Optional - Start Date (YYYY-MM-DD)
    stop_date: Optional[date] = None,  # Optional - Stop date (YYYY-MM-DD)
    encounter_id: Optional[int] = None,  # Optional - Map with encounter
    dispense_unit: Optional[str] = None,  # Optional - Dispense unit (specific values)
    rx_sig: Optional[List[Dict[str, Any]]] = None,  # Optional - JSONArray dosages
    prior_authorization_code: Optional[str] = None,  # Optional - Prior Authorization Code
    prior_authorization_status: Optional[str] = None,  # Optional - A|D|F|N|R
    note_to_pharmacy: Optional[str] = None,  # Optional - Note to Pharmacy
    csa: Optional[int] = None,  # Optional - Controlled drug (1-5) or non controlled (0)
    is_supplies: Optional[bool] = None,  # Optional - Medication or supplements/injections/syringes
    ndc: Optional[int] = None,  # Optional - National Drug Code
    route: Optional[str] = None,  # Optional - Intake route (specific values)
    dose_form: Optional[str] = None,  # Optional - Dose form (specific values)
    dosage_unit: Optional[str] = None,  # Optional - Dosage unit (specific values)
    dosage: Optional[float] = None,  # Optional - Dosage amount
    sig_frequency: Optional[str] = None,  # Optional - Frequency (QD|BID|TID|etc)
    sig_intake: Optional[str] = None,  # Optional - Intake unit (AC|PC|WM|etc)
    duration: Optional[int] = None,  # Optional - Duration of drug
    duration_unit: Optional[str] = None,  # Optional - Day(s)|Week(s)|Month(s)
) -> Dict[str, Any]:
    """
    Add medications for a patient in CharmHealth.
    
    Required parameters:
    - drug_name: Drug name
    - is_active: Medication status (true/false)
    - directions: Directions to use medication
    - dispense: Dispense of medication (float)
    - refills: Refills pattern ([0-9]{1,2} | PRN | -1)
    - substitute_generic: Whether other brands are allowed (true/false)
    - manufacturing_type: "Manufactured" or "Compounded"
    
    Optional parameters include trade_name, strength_description, dates, dosage info, etc.
    
    dispense_unit values: Applicator, Capsule, Blister, Caplet, etc.
    route values: buccal, oral, injectable, topical, etc.
    dose_form values: tablet, capsule, liquid, cream, etc.
    dosage_unit values: tablet(s), capsule(s), ml, mg, etc.
    sig_frequency values: QD, BID, TID, QID, PRN, etc.
    sig_intake values: AC, PC, WM, AM, PM, HS, etc.
    duration_unit values: Day(s), Week(s), Month(s)
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Use build_params_from_locals to build the medication data
            medication_data = build_params_from_locals(locals())
            medication_data.pop("patient_id")
            # API expects a JSONArray, so wrap in array
            data = [medication_data]
            
            response = await client.post(f"/patients/{patient_id}/medications", data=data)
            logger.info(f"Tool call completed for add_medication, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_medication: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def list_medications(
    patient_id: str,
    encounter_id: Optional[str] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,
    sort_order: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get medications for a patient in CharmHealth.

    This function gets all medications for a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to get medications for
        encounter_id (Optional[str]): The unique identifier for the encounter to get medications for
    """
    async with CharmHealthAPIClient() as client:
        try:
            endpoint = f"/patients/{patient_id}/medications"
            params = {}
            if encounter_id:
                params["encounter_id"] = encounter_id
            if page:
                params["page"] = page
            if per_page:
                params["per_page"] = per_page
            if sort_order:
                params["sort_order"] = sort_order
            response = await client.get(endpoint, params=params)
            logger.info(f"Tool call completed for list_medications, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in list_medications: {e}")
            return {"error": str(e)}
    

@patient_management_mcp.tool
@with_tool_metrics()
async def edit_medication(
    patient_id: str,
    medication_id: str,
    drug_name: Optional[str] = None,
    is_active: Optional[bool] = None,
    directions: Optional[str] = None,
    is_directions_edited: Optional[bool] = None,
    dispense: Optional[float] = None,
    refills: Optional[str] = None,
    substitute_generic: Optional[bool] = None,
    manufacturing_type: Optional[str] = None,
    trade_name: Optional[str] = None,
    strength_description: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Edit a medication in CharmHealth.

    This function edits a medication in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to edit the medication for
        medication_id (str): The unique identifier for the medication to edit
        drug_name (Optional[str]): The name of the drug to edit
        is_active (Optional[bool]): The status of the medication (true/false)
        directions (Optional[str]): The directions to use the medication
        is_directions_edited (Optional[bool]): Whether the directions have been edited (true/false)
        dispense (Optional[float]): The dispense of the medication
        refills (Optional[str]): The refills of the medication
    """
    async with CharmHealthAPIClient() as client:
        try:
            data = build_params_from_locals(locals())
            data.pop("patient_id")
            response = await client.put(f"/patients/{patient_id}/medications/{medication_id}", data=data)
            logger.info(f"Tool call completed for edit_medication, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in edit_medication: {e}")
            return {"error": str(e)}
    
@patient_management_mcp.tool
@with_tool_metrics()
async def delete_medication(
    patient_id: str,
    medication_id: str,
) -> Dict[str, Any]:
    """
    Delete a medication in CharmHealth.

    This function deletes a medication in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to delete the medication for
        medication_id (str): The unique identifier for the medication to delete
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.delete(f"/patients/{patient_id}/medications/{medication_id}")
            logger.info(f"Tool call completed for delete_medication, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in delete_medication: {e}")
            return {"error": str(e)}
    
# =========================== PATIENT LAB RESULTS ===========================
@patient_management_mcp.tool
@with_tool_metrics()
async def list_lab_results(
    reviewer_id: Optional[int] = None,  # Optional - Reviewer ID
    patient_id: Optional[int] = None,   # Optional - Patient ID
    status: Optional[int] = None,       # Optional - 0 or 2
    start_index: Optional[int] = None,  # Optional - Start index for pagination
    no_of_records: Optional[int] = None, # Optional - Number of records to return
    sort_by: Optional[str] = None,      # Optional - DATE | FULL_NAME
    is_ascending: Optional[bool] = None, # Optional - Sort order
) -> Dict[str, Any]:
    """
    List lab results from CharmHealth.
    
    By default, this API returns lab results sorted by result date with maximum of 25 records.
    
    Optional parameters:
    - reviewer_id: Filter by reviewer ID
    - patient_id: Filter by patient ID  
    - status: Filter by status (0 or 2)
    - start_index: Starting index for pagination
    - no_of_records: Number of records to return
    - sort_by: Sort field (DATE | FULL_NAME)
    - is_ascending: Sort order (true for ascending, false for descending)
    """
    async with CharmHealthAPIClient() as client:
        try:
            params = build_params_from_locals(locals())
            response = await client.get("/labs/results", params=params)
            logger.info(f"Tool call completed for list_lab_results, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in list_lab_results: {e}")
            return {"error": str(e)}
    
@patient_management_mcp.tool
@with_tool_metrics()
async def get_detailed_lab_result(
    group_id: Optional[str] = None,
    lab_order_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get detailed lab result from CharmHealth.

    This function gets a detailed lab result from CharmHealth.
    
    Args:
        group_id (Optional[str]): The unique identifier for the group to get the lab result for
        lab_order_id (Optional[str]): The unique identifier for the lab order to get the lab result for
    """
    async with CharmHealthAPIClient() as client:
        try:
            if group_id:
                endpoint = f"/labs/results/{group_id}"
            elif lab_order_id:
                endpoint = f"/labs/order/results/{lab_order_id}"
            else:
                return {"error": "Either group_id or lab_order_id is required."}
            response = await client.get(endpoint)
            logger.info(f"Tool call completed for get_detailed_lab_result, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in get_detailed_lab_result: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def add_lab_result(
    patient_id: int,  # Required - Patient Identifier
    result_details: Dict[str, Any],  # Required - JSONObject with lab result details
) -> Dict[str, Any]:
    """
    Add lab results to a patient in CharmHealth.
    
    Required parameters:
    - patient_id: Patient Identifier (Long)
    - result_details: JSONObject containing lab result details
    
    result_details structure:
    {
        "group_comments": str,
        "report_status": str (e.g., "Final"),
        "accession_number": str,
        "no_pdf": str ("true"/"false"),
        "tests": [
            {
                "lab_id": str,
                "lab_name": str,
                "test_id": str,
                "test_name": str,
                "lab_record_id": str,
                "lab_record_code": str,
                "patient_id": str,
                "date": str (YYYY-MM-DD HH:mm:ss),
                "test_comments": str,
                "facility_id": str,
                "interpretation": str,
                "reviewer_details": {
                    "reviewer_id": str
                },
                "test_tags": [],
                "test_parameters": [
                    {
                        "param_val": str,
                        "param_comments": str,
                        "parameter_name": str,
                        "med_param_id": str,
                        "lab_param_id": str,
                        "loinc_code": str,
                        "lab_param_code": str,
                        "recordunit": str,
                        "ref_range": str,
                        "ref_min": str,
                        "ref_max": str,
                        "interpretation": str
                    }
                ]
            }
        ]
    }
    """
    async with CharmHealthAPIClient() as client:
        try:
            data = build_params_from_locals(locals())
            response = await client.post("/labs/results/upload", data=data)
            logger.info(f"Tool call completed for add_lab_result, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_lab_result: {e}")
            return {"error": str(e)}


# =========================== PATIENT DIAGNOSES ===========================
@patient_management_mcp.tool
@with_tool_metrics()
async def add_diagnosis(
    patient_id: str,
    name: str,
    code: str,
    code_type: str,
    status: Optional[str] = None,
    comments: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    encounter_id: Optional[int] = None,
    diagnosis_order: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Add a diagnosis to a patient in CharmHealth.
    
    Args:
        patient_id: Patient identifier
        name: Diagnosis name (required)
        code: Diagnosis code (required)
        code_type: Diagnosis code type (required)
        status: Diagnosis status (Active | Inactive | Resolved)
        comments: Comments
        from_date: Diagnosis start date (YYYY-MM-DD format)
        to_date: Diagnosis end date (YYYY-MM-DD format)
        encounter_id: Encounter identifier
        diagnosis_order: Position of diagnosis
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Use build_params_from_locals to build the diagnosis data
            diagnosis_data = build_params_from_locals(locals())
            
            # Convert diagnosis_order to string as required by API
            if "diagnosis_order" in diagnosis_data and diagnosis_data["diagnosis_order"] is not None:
                diagnosis_data["diagnosis_order"] = str(diagnosis_data["diagnosis_order"])
            diagnosis_data.pop("patient_id")
            # API expects a JSONArray, so wrap in array
            data = [diagnosis_data]

            logger.info(f"Diagnosis data: {data}")
            response = await client.post(f"/patients/{patient_id}/diagnoses", data=data)
            logger.info(f"Tool call completed for add_diagnosis, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_diagnosis: {e}")
            return {"error": str(e) + " with " + str(data)}
    

@patient_management_mcp.tool
@with_tool_metrics()
async def get_diagnoses(
    patient_id: str,
    encounter_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get diagnoses for a patient in CharmHealth.

    This function gets all diagnoses for a patient in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to get diagnoses for
        encounter_id (Optional[str]): The unique identifier for the encounter to get diagnoses for
    """
    async with CharmHealthAPIClient() as client:
        try:
            endpoint = f"/patients/{patient_id}/diagnoses"
            if encounter_id:
                endpoint += f"?encounter_id={encounter_id}"
            response = await client.get(endpoint)
            logger.info(f"Tool call completed for get_diagnoses, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in get_diagnoses: {e}")
            return {"error": str(e)}


@patient_management_mcp.tool
@with_tool_metrics()
async def update_diagnosis(
    patient_id: str,
    diagnosis_id: str,
    status: Optional[str] = None,
    comments: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update a diagnosis in CharmHealth.

    This function updates a diagnosis in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to update the diagnosis for
        diagnosis_id (str): The unique identifier for the diagnosis to update
    """
    async with CharmHealthAPIClient() as client:
        try:
            data = build_params_from_locals(locals())
            data.pop("patient_id")
            response = await client.put(f"/patients/{patient_id}/diagnoses/{diagnosis_id}", data=data)
            logger.info(f"Tool call completed for update_diagnosis, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in update_diagnosis: {e}")
            return {"error": str(e)}
    
@patient_management_mcp.tool
@with_tool_metrics()
async def delete_diagnosis(
    patient_id: str,
    diagnosis_id: str,
) -> Dict[str, Any]:
    """
    Delete a diagnosis in CharmHealth.

    This function deletes a diagnosis in CharmHealth.
    
    Args:
        patient_id (str): The unique identifier for the patient to delete the diagnosis for
        diagnosis_id (str): The unique identifier for the diagnosis to delete
    """
    async with CharmHealthAPIClient() as client:
        try:
            response = await client.delete(f"/patients/{patient_id}/diagnoses/{diagnosis_id}")
            logger.info(f"Tool call completed for delete_diagnosis, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in delete_diagnosis: {e}")
            return {"error": str(e)}


# =========================== PATIENT VITALS ===========================
@patient_management_mcp.tool
@with_tool_metrics()
async def add_vitals(
    patient_id: str,
    vitals: List[Dict[str, str]],  # Required - List of vitals to add
    encounter_id: Optional[str] = None,  # Required if entry_date not provided
    entry_date: Optional[date] = None,  # Required if encounter_id not provided (YYYY-MM-DD)
) -> Dict[str, Any]:
    """
    Add vitals for a patient in CharmHealth.
    
    Either encounter_id OR entry_date must be provided.
    - If encounter_id is provided, vitals will be associated with that encounter
    - If entry_date is provided without encounter_id, vitals will be added for that specific date
    
    Args:
        patient_id: Patient identifier
        vitals: List of vital measurements, each containing:
            - vital_name: Name of the vital (required)
            - vital_value: Value of vital (optional)
            - vital_unit: Unit of vital (optional)
        encounter_id: Encounter ID if associating with an encounter
        entry_date: Date for vitals entry (YYYY-MM-DD format) if not using encounter_id
    
    Example vitals format:
    [
        {
            "vital_name": "Weight",
            "vital_unit": "kgs", 
            "vital_value": "80"
        },
        {
            "vital_name": "Height",
            "vital_unit": "cms",
            "vital_value": "173"
        },
        {
            "vital_name": "BMI",
            "vital_unit": "",
            "vital_value": "26.73"
        },
        {
            "vital_name": "Temp",
            "vital_unit": "F",
            "vital_value": "98"
        },
        {
            "vital_name": "Systolic BP",
            "vital_unit": "mmHg",
            "vital_value": "120"
        },
        {
            "vital_name": "Diastolic BP", 
            "vital_unit": "mmHg",
            "vital_value": "80"
        },
        {
            "vital_name": "Pulse Rate",
            "vital_unit": "bpm",
            "vital_value": "80"
        }
    ]
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Validate that either encounter_id or entry_date is provided
            if not encounter_id and not entry_date:
                return {"error": "Either encounter_id or entry_date must be provided"}
            
            # Build the request data
            vital_entry = {
                "vitals": vitals
            }
            
            if encounter_id:
                vital_entry["encounter_id"] = encounter_id
            if entry_date:
                vital_entry["entry_date"] = entry_date.isoformat()
            
            # API expects a JSONArray, so wrap in array
            data = [vital_entry]
            
            response = await client.post(f"/patients/{patient_id}/vitals", data=data)
            logger.info(f"Tool call completed for add_vitals, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_vitals: {e}")
            return {"error": str(e)}
        

# =========================== PATIENT APPOINTMENTS ===========================

@patient_management_mcp.tool
@with_tool_metrics()
async def add_appointment(
    patient_id: str,
    facility_id: str,
    member_id: str,
    mode: str,  # Required - Phone call|In Person|Video Consult
    repetition: str,  # Required - Type of appointment (Single Date, Daily, Weekly, etc.)
    appointment_status: str,  # Required - Appointment Status (Confirmed, Pending, etc.)
    start_date: date,  # Required - Appointment start date (YYYY-MM-DD)
    start_time: str,  # Required - Appointment start time (HH:MM period)
    duration_in_minutes: int,  # Required - Appointment Duration
    end_date: Optional[date] = None,  # Optional - Appointment end date (YYYY-MM-DD)
    weekly_days: Optional[List[Dict[str, str]]] = None,  # Optional - [{"week_day": "Monday"}] for periodic appointments
    reason: Optional[str] = None,  # Optional - Reason for the appointment
    message_to_patient: Optional[str] = None,  # Optional - Message to patient
    questionnaire: Optional[List[Dict[str, int]]] = None,  # Optional - [{"questionnaire_id": int}]
    consent_forms: Optional[List[Dict[str, int]]] = None,  # Optional - [{"file_id": int}]
    visit_type_id: Optional[int] = None,  # Optional - Visit types of appointment
    frequency: Optional[str] = None,  # Optional - daily|weekly
    resource_id: Optional[int] = None,  # Optional - Resource room id
    provider_double_booking: Optional[str] = None,  # Optional - "allow" to override double booking check
    resource_double_booking: Optional[str] = None,  # Optional - "allow" to override resource double booking check
    receipt_id: Optional[int] = None,  # Optional - Receipt details of appointment
) -> Dict[str, Any]:
    """
    Add an appointment for a patient in CharmHealth.
    
    Required parameters:
    - patient_id: Patient Identifier
    - facility_id: Facility Identifier
    - member_id: Provider Identifier
    - mode: Appointment Mode ("Phone call" | "In Person" | "Video Consult")
    - repetition: Type of appointment ("Single Date", "Daily", "Weekly", etc.)
    - appointment_status: Appointment Status ("Confirmed", "Pending", etc.)
    - start_date: Appointment start date (YYYY-MM-DD format)
    - start_time: Appointment start time (HH:MM period format, e.g., "12:10 PM")
    - duration_in_minutes: Appointment Duration
    
    Optional parameters:
    - end_date: Appointment end date for recurring appointments
    - weekly_days: List of weekdays for periodic appointments [{"week_day": "Sunday|Monday|..."}]
    - reason: Reason for the appointment
    - message_to_patient: Message to patient
    - questionnaire: Questionnaires associated [{"questionnaire_id": <id>}]
    - consent_forms: Consent forms associated [{"file_id": <id>}]
    - visit_type_id: Visit type identifier
    - frequency: "daily" or "weekly" for recurring appointments
    - resource_id: Resource room identifier
    - provider_double_booking: Set to "allow" to override double booking check
    - resource_double_booking: Set to "allow" to override resource double booking check
    - receipt_id: Receipt details identifier
    
    Example usage:
    - Basic appointment: patient_id="123", facility_id="456", member_id="789", 
      mode="In Person", repetition="Single Date", appointment_status="Confirmed",
      start_date=date(2024, 8, 8), start_time="12:10 PM", duration_in_minutes=60
    - Weekly recurring: Same as above but repetition="Weekly", frequency="weekly",
      weekly_days=[{"week_day": "Monday"}, {"week_day": "Wednesday"}]
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Build the appointment data using build_params_from_locals
            appointment_data = build_params_from_locals(locals())
            
            
            if start_date:
                appointment_data["start_date"] = start_date.isoformat()
            if end_date:
                appointment_data["end_date"] = end_date.isoformat()
            
            
            data = {"data": appointment_data}
            
            response = await client.post("/appointments", data=data)
            logger.info(f"Tool call completed for add_appointment, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in add_appointment: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def reschedule_appointment(
    appointment_id: str,
    facility_id: str,
    patient_id: str,
    member_id: str,
    mode: str,  # Required - Phone call|In Person|Video Consult
    repetition: str,  # Required - Single Date, Period
    start_date: date,  # Required - Appointment start date (YYYY-MM-DD)
    start_time: str,  # Required - Appointment start time (HH:MM period)
    duration_in_minutes: int,  # Required - Appointment duration (max 4 digits)
    appointment_status: str,  # Required - Confirmed, Cancelled, Consulted, etc.
    visit_type_id: int,  # Required - Visit types of appointment
    reason: Optional[str] = None,  # Optional - Reason for appointment (max 1000 chars)
    source: Optional[str] = None,  # Optional - Appointment source (max 10 chars)
    message_to_patient: Optional[str] = None,  # Optional - Message to patient (max 1000 chars)
    questionnaire: Optional[List[Dict[str, int]]] = None,  # Optional - [{"questionnaire_id": int}]
    consent_forms: Optional[List[Dict[str, int]]] = None,  # Optional - [{"file_id": int}]
    resource_id: Optional[int] = None,  # Optional - Resource Identifier
    provider_double_booking: Optional[str] = None,  # Optional - "allow" to override double booking check
    resource_double_booking: Optional[str] = None,  # Optional - "allow" to override resource double booking check
) -> Dict[str, Any]:
    """
    Reschedule an existing appointment in CharmHealth.
    
    Required parameters:
    - appointment_id: Existing appointment identifier to reschedule
    - facility_id: Facility Identifier
    - patient_id: Patient Identifier  
    - member_id: Member/Provider Identifier
    - mode: Appointment Mode ("Phone call" | "In Person" | "Video Consult")
    - repetition: Type of appointment ("Single Date" | "Period")
    - start_date: New appointment start date (YYYY-MM-DD format)
    - start_time: New appointment start time (HH:MM period format, e.g., "07:30 AM")
    - duration_in_minutes: Appointment duration in minutes (maximum 4 digits)
    - appointment_status: Appointment Status ("Confirmed", "Cancelled", "Consulted", etc.)
    - visit_type_id: Visit type identifier
    
    Optional parameters:
    - reason: Reason for appointment (maximum 1000 characters)
    - source: Appointment source (maximum 10 characters)
    - message_to_patient: Message to patient (maximum 1000 characters)
    - questionnaire: Questionnaires associated [{"questionnaire_id": <id>}]
    - consent_forms: Consent forms associated [{"file_id": <id>}]
    - resource_id: Resource identifier
    - provider_double_booking: Set to "allow" to override double booking check
    - resource_double_booking: Set to "allow" to override resource double booking check
    
    Example usage:
    reschedule_appointment(
        appointment_id="100004000000017379",
        facility_id="100001000000000153", 
        patient_id="100001000000000599",
        member_id="100001000000000101",
        mode="Phone Call",
        repetition="Single Date",
        start_date=date(2021, 3, 2),
        start_time="07:30 AM",
        duration_in_minutes=8,
        appointment_status="Confirmed",
        visit_type_id=100001000000008001,
        reason="auto immune hashimo thyroid",
        message_to_patient="take tests for anti TPO and TSH"
    )
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Build the appointment data using build_params_from_locals
            appointment_data = build_params_from_locals(locals())
            
            # Remove appointment_id from the data payload as it's in the URL
            appointment_data.pop("appointment_id", None)
            
            # Convert date objects to ISO format strings as required by API
            if start_date:
                appointment_data["start_date"] = start_date.isoformat()
            
            # Wrap the data in the required "data" object structure  
            data = {"data": appointment_data}
            
            response = await client.post(f"/appointment/{appointment_id}/reschedule", data=data)
            logger.info(f"Tool call completed for reschedule_appointment, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in reschedule_appointment: {e}")
            return {"error": str(e)}
        
@patient_management_mcp.tool
@with_tool_metrics()
async def cancel_appointment(
    appointment_id: str,
    reason: str,  # Required - Reason for cancellation (max length 400)
    delete_type: Optional[str] = None,  # Optional - Current|Entire
) -> Dict[str, Any]:
    """
    Cancel an existing appointment in CharmHealth.
    
    Required parameters:
    - appointment_id: Existing appointment identifier to cancel
    - reason: Reason for cancellation (maximum 400 characters)
    
    Optional parameters:
    - delete_type: Type of cancellation ("Current" | "Entire")
      - "Current": Cancel only the current appointment
      - "Entire": Cancel the entire series (for recurring appointments)
    
    Example usage:
    cancel_appointment(
        appointment_id="100004000000017379",
        reason="Booked for different date",
        delete_type="Current"
    )
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Build the cancellation data
            data = {
                "reason": reason
            }
            
            # Add delete_type if provided
            if delete_type:
                data["delete_type"] = delete_type
            
            response = await client.post(f"/appointments/{appointment_id}/cancel", data=data)
            logger.info(f"Tool call completed for cancel_appointment, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in cancel_appointment: {e}")
            return {"error": str(e)}

@patient_management_mcp.tool
@with_tool_metrics()
async def list_appointments(
    start_date: date,  # Required - Start date (yyyy-mm-dd format)
    end_date: date,  # Required - End date (yyyy-mm-dd format)
    facility_ids: str,  # Required - Facility IDs separated by commas
    patient_id: Optional[int] = None,  # Optional - Patient Identifier
    member_ids: Optional[str] = None,  # Optional - Provider IDs separated by commas
    status_ids: Optional[str] = None,  # Optional - Status IDs separated by commas or 'ALL'
    visit_type_ids: Optional[str] = None,  # Optional - Visit type IDs separated by commas
    modified_time: Optional[int] = None,  # Optional - Modified time
    modified_time_greater_than: Optional[int] = None,  # Optional - Modified time greater than
    modified_time_less_than: Optional[int] = None,  # Optional - Modified time less than
    modified_time_greater_equals: Optional[int] = None,  # Optional - Modified time greater equals
    modified_time_less_equals: Optional[int] = None,  # Optional - Modified time less equals
    time_of_creation: Optional[int] = None,  # Optional - Creation time
    time_of_creation_greater_than: Optional[int] = None,  # Optional - Creation time greater than
    time_of_creation_less_than: Optional[int] = None,  # Optional - Creation time less than
    time_of_creation_greater_equals: Optional[int] = None,  # Optional - Creation time greater equals
    time_of_creation_less_equals: Optional[int] = None,  # Optional - Creation time less equals
    referral_source: Optional[str] = None,  # Optional - Referral Source
    referral_specific_source: Optional[str] = None,  # Optional - Specific Source
    sort_order: Optional[str] = None,  # Optional - A (Ascending) | D (Descending)
    sort_column: Optional[str] = None,  # Optional - appointment_date
    page: Optional[int] = None,  # Optional - Page number
    per_page: Optional[int] = None,  # Optional - Records per page
) -> Dict[str, Any]:
    """
    List appointments in CharmHealth with flexible filtering options.
    
    Required parameters:
    - start_date: Start date for appointment search (yyyy-mm-dd format)
    - end_date: End date for appointment search (yyyy-mm-dd format)  
    - facility_ids: Facility IDs separated by commas (e.g., "123,456,789")
    
    Optional filtering parameters:
    - patient_id: Filter by specific patient
    - member_ids: Filter by specific providers (comma-separated IDs)
    - status_ids: Filter by appointment status (comma-separated IDs or 'ALL')
    - visit_type_ids: Filter by visit types (comma-separated IDs)
    
    Time-based filtering:
    - modified_time: Filter by modification time
    - modified_time_greater_than/less_than/greater_equals/less_equals: Modification time variants
    - time_of_creation: Filter by creation time
    - time_of_creation_greater_than/less_than/greater_equals/less_equals: Creation time variants
    
    Other filters:
    - referral_source: Filter by referral source
    - referral_specific_source: Filter by specific referral source
    - sort_order: "A" for Ascending, "D" for Descending
    - sort_column: Currently supports "appointment_date"
    - page: Page number for pagination
    - per_page: Number of records per page
    
    Common use cases:
    
    # All appointments for specific facilities in date range:
    list_appointments(
        start_date=date(2020, 7, 1),
        end_date=date(2020, 7, 15), 
        facility_ids="5130000xxxx9005"
    )
    
    # All appointments for specific provider across facilities:
    list_appointments(
        start_date=date(2020, 7, 1),
        end_date=date(2020, 7, 15),
        facility_ids="123,456,789",
        member_ids="provider_id_123"
    )
    
    # All appointments for specific patient:
    list_appointments(
        start_date=date(2020, 7, 1),
        end_date=date(2020, 7, 15),
        facility_ids="123",
        patient_id=1884000004241057
    )
    
    # Confirmed appointments only:
    list_appointments(
        start_date=date(2020, 7, 1),
        end_date=date(2020, 7, 15),
        facility_ids="123",
        status_ids="confirmed_status_id"
    )
    """
    async with CharmHealthAPIClient() as client:
        try:
            # Build query parameters using build_params_from_locals
            params = build_params_from_locals(locals())
            
            # Convert date objects to the required string format
            if start_date:
                params["start_date"] = start_date.strftime("%Y-%m-%d")
            if end_date:
                params["end_date"] = end_date.strftime("%Y-%m-%d")
            
            response = await client.get("/appointments", params=params)
            logger.info(f"Tool call completed for list_appointments, with message {response.get('message', '')} and code {response.get('code', '')}")
            return response
        except Exception as e:
            logger.error(f"Error in list_appointments: {e}")
            return {"error": str(e)}

