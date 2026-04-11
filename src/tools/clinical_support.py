from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals, strip_empty_values
from common.filtering import filter_items
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

clinical_support_mcp = FastMCP(name="CharmHealth Clinical Support MCP Server")

@clinical_support_mcp.tool
@with_tool_metrics()
async def managePatientNotes(
    action: Literal["add", "list", "update", "delete"],
    patient_id: str,
    record_id: Optional[str] = None,
    notes: Optional[str] = None,

    # List filters
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient notes.

    <usecase>
    Quick clinical note management for important patient information - add care notes, provider communications,
    and clinical observations that need to be highlighted across all patient interactions.
    </usecase>
    
    <instructions>
    Actions:
    - "add": Add new clinical note (requires notes content)
    - "list": Show all patient notes (optionally filter by date range)
    - "update": Modify existing note (requires record_id + notes content)
    - "delete": Remove note (requires record_id). Ask the user if they are sure they want to delete the note before proceeding.
    
    Use for: Important care instructions, provider alerts, patient preferences, social determinants
    Formal encounter notes should use manageEncounter() instead

    List filters:
    - from_date / to_date: e.g., from_date="2025-01-01", to_date="2025-12-31"
    - limit: e.g., limit=50

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    # Extract user tokens and environment from HTTP headers (proper FastMCP way)
    access_token = None
    refresh_token = None
    base_url = None
    token_url = None
    
    try:
        headers = get_http_headers()
        access_token = headers.get('x-user-access-token')
        refresh_token = headers.get('x-user-refresh-token')
        base_url = headers.get('x-charmhealth-base-url')
        token_url = headers.get('x-charmhealth-token-url')
        client_secret = headers.get('x-charmhealth-client-secret')
        accounts_server = headers.get('x-charmhealth-accounts-server')
        
        # If accounts_server is provided, use it for token URL (mobile flow)
        if accounts_server:
            token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"
        
        # Normalize base URL to include API path
        if base_url and not base_url.endswith('/api/ehr/v1'):
            base_url = base_url.rstrip('/') + '/api/ehr/v1'
        
        if access_token:
            logger.info(f"managePatientNotes using user credentials")
        else:
            logger.info("managePatientNotes using environment variable credentials")
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
                    response = await client.get(f"/patients/{patient_id}/quicknotes")
                    notes_list = response.get("quick_notes") or []
                    total_count = len(notes_list)

                    wrappers = []
                    for n in notes_list:
                        note_date = (n or {}).get("created_date") or (n or {}).get("date") or (n or {}).get("createdDate")
                        wrappers.append({**(n or {}), "_orig": n, "note_date": note_date})

                    filtered_wrappers = wrappers
                    if from_date:
                        filtered_wrappers = filter_items(filtered_wrappers, {"note_date": {"op": "gte", "value": from_date}})["items"]
                    if to_date:
                        filtered_wrappers = filter_items(filtered_wrappers, {"note_date": {"op": "lte", "value": to_date}})["items"]

                    filtered_count = len(filtered_wrappers)
                    limited = filter_items(filtered_wrappers, filters=None, limit=limit)["items"] if limit is not None else filtered_wrappers

                    response["quick_notes"] = [w.get("_orig", w) for w in limited]
                    response["total_count"] = total_count
                    response["filtered_count"] = filtered_count

                    if response.get("quick_notes"):
                        response["guidance"] = (
                            f"Patient has {total_count} clinical notes; {filtered_count} match the provided filters."
                            " These are visible to all providers during patient care. Use action='add' for new important clinical information."
                        )
                    else:
                        response["guidance"] = "No clinical notes found matching the provided filters. Use action='add' to document important patient information for provider awareness."
                    return strip_empty_values(response)
                    
                case "add":
                    if not notes:
                        return {
                            "error": "Notes content required",
                            "guidance": "Provide the clinical note content. Use clear, professional language as this will be visible to all providers."
                        }
                    
                    response = await client.post(f"/patients/{patient_id}/quicknotes", data={"notes": notes})
                    if response.get("data"):
                        response["guidance"] = f"Clinical note added successfully. This important information is now visible to all providers during patient care. For detailed encounter documentation, use manageEncounter()()."
                    return strip_empty_values(response)
                    
                case "update":
                    if not record_id or not notes:
                        return {
                            "error": "record_id and notes content required for updates",
                            "guidance": "Use action='list' to find the note record_id, then provide the updated notes content."
                        }
                    
                    response = await client.put(f"patients/quicknotes/{record_id}", data={"notes": notes})
                    if response.get("code") == "0":
                        response["guidance"] = f"Clinical note {record_id} updated successfully. Updated information is now available to all providers."
                    return strip_empty_values(response)
                    
                case "delete":
                    if not record_id:
                        return {
                            "error": "record_id required for deletion",
                            "guidance": "Use action='list' to find the note record_id first."
                        }
                    
                    response = await client.delete(f"patients/quicknotes/{record_id}")
                    if response.get("code") == "0":
                        response["guidance"] = f"Clinical note {record_id} deleted successfully. Information is no longer visible to providers."
                    return strip_empty_values(response)
                    
        except Exception as e:
            logger.error(f"Error in managePatientNotes: {e}")
            return {
                "error": str(e),
                "guidance": f"Clinical note {action} failed. Consider documenting important patient information for provider awareness."
            }

@clinical_support_mcp.tool
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

    # List filters
    type_filter: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,
    
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient recalls.

    <usecase>
    Patient recall and follow-up management - schedule preventive care reminders, follow-up appointments,
    and care plan reminders. Ensures patients receive timely care according to clinical guidelines.
    </usecase>
    
    <instructions>
    Actions:
    - "add": Schedule new recall (requires recall_type, notes, provider_id, facility_id)
    - "list": Show all patient recalls (optionally filter by type/date range)
    - "update": Modify existing recall (requires record_id, recall_type, notes — use action='list' first to get current values, then pass all required fields with your changes)
    - "delete": Remove recall (requires record_id). Ask the user if they are sure they want to delete the recall before proceeding.
    
    recall_type is a free-form string set by the practice (e.g. "Office Visit", "Follow-up", "Imaging", "Annual Physical"). Do not invent verbose names — use short descriptive terms.
    Scheduling: PREFER recall_date (ISO date string, e.g. "2026-07-10"). If using recall_time/recall_timeunit instead, recall_period is also REQUIRED (e.g. recall_time=3, recall_timeunit="Months", recall_period="after") — omitting recall_period causes a server error.
    Reminder timing: email_reminder_before/text_reminder_before in days (e.g., 7 for one week)
    Use getPracticeInfo() to get valid provider_id and facility_id values

    List filters:
    - type_filter: e.g., type_filter="Annual Physical"
    - from_date / to_date: e.g., from_date="2025-01-01", to_date="2025-12-31" (compares against recall_date when available)
    - limit: e.g., limit=25

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    # Extract user tokens and environment from HTTP headers (proper FastMCP way)
    access_token = None
    refresh_token = None
    base_url = None
    token_url = None
    
    try:
        headers = get_http_headers()
        access_token = headers.get('x-user-access-token')
        refresh_token = headers.get('x-user-refresh-token')
        base_url = headers.get('x-charmhealth-base-url')
        token_url = headers.get('x-charmhealth-token-url')
        client_secret = headers.get('x-charmhealth-client-secret')
        accounts_server = headers.get('x-charmhealth-accounts-server')
        
        # If accounts_server is provided, use it for token URL (mobile flow)
        if accounts_server:
            token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"
        
        # Normalize base URL to include API path
        if base_url and not base_url.endswith('/api/ehr/v1'):
            base_url = base_url.rstrip('/') + '/api/ehr/v1'
        
        if access_token:
            logger.info(f"managePatientRecalls using user credentials")
        else:
            logger.info("managePatientRecalls using environment variable credentials")
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
                    response = await client.get(f"/patients/{patient_id}/recalls")
                    recalls = response.get("recall") or []
                    total_count = len(recalls)

                    wrappers = []
                    for r in recalls:
                        recall_type_val = (r or {}).get("recall_type") or (r or {}).get("type")
                        recall_date_val = (r or {}).get("recall_date") or (r or {}).get("date") or (r or {}).get("created_date")
                        wrappers.append({
                            **(r or {}),
                            "_orig": r,
                            "recall_type": recall_type_val,
                            "recall_date": recall_date_val,
                        })

                    filters: Dict[str, Any] = {}
                    if type_filter:
                        filters["recall_type"] = type_filter

                    filtered_wrappers = wrappers
                    if filters:
                        filtered_wrappers = filter_items(filtered_wrappers, filters=filters)["items"]
                    if from_date:
                        filtered_wrappers = filter_items(filtered_wrappers, {"recall_date": {"op": "gte", "value": from_date}})["items"]
                    if to_date:
                        filtered_wrappers = filter_items(filtered_wrappers, {"recall_date": {"op": "lte", "value": to_date}})["items"]

                    filtered_count = len(filtered_wrappers)
                    limited = filter_items(filtered_wrappers, filters=None, limit=limit)["items"] if limit is not None else filtered_wrappers

                    response["recall"] = [w.get("_orig", w) for w in limited]
                    response["total_count"] = total_count
                    response["filtered_count"] = filtered_count

                    if response.get("recall"):
                        recall_count = len(response["recall"])
                        active_recalls = [r for r in response["recall"] if str(r.get("status", "")).lower() == "active"]
                        
                        guidance = f"Patient has {recall_count} total recalls, {len(active_recalls)} active"
                        guidance += ". These ensure timely preventive care and follow-up visits. Schedule appointments with manageAppointments() when recalls are due."
                        response["guidance"] = guidance
                    else:
                        response["guidance"] = "No recalls scheduled matching the provided filters. Use action='add' to schedule preventive care reminders based on clinical guidelines and patient needs."
                    return strip_empty_values(response)
                    
                case "add":
                    required = [recall_type, notes, provider_id, facility_id]
                    if not all(required):
                        return {
                            "error": "Missing required fields for recall",
                            "guidance": "For recalls, provide: recall_type, notes, provider_id, and facility_id. Use getPracticeInfo() to get valid provider and facility IDs."
                        }

                    # Build payload with only present fields — CharmHealth 500s on null values
                    recall_entry: Dict[str, Any] = {
                        "recall_type": recall_type,
                        "notes": notes,
                        "provider_id": int(provider_id),
                        "facility_id": int(facility_id),
                    }
                    if recall_date:
                        recall_entry["recall_date"] = recall_date.isoformat()
                    if recall_time is not None:
                        recall_entry["recall_time"] = recall_time
                    if recall_timeunit:
                        recall_entry["recall_timeunit"] = recall_timeunit
                    if recall_period:
                        recall_entry["recall_period"] = recall_period
                    if encounter_id:
                        recall_entry["encounter_id"] = int(encounter_id)
                    if send_email_reminder is not None:
                        recall_entry["send_email_reminder"] = send_email_reminder
                    if email_reminder_before is not None:
                        recall_entry["email_reminder_before"] = str(email_reminder_before)
                    if send_text_reminder is not None:
                        recall_entry["send_text_reminder"] = send_text_reminder
                    if text_reminder_before is not None:
                        recall_entry["text_reminder_before"] = str(text_reminder_before)

                    response = await client.post(f"/patients/{patient_id}/recalls", data=[recall_entry])
                    if response.get("recalls"):
                        reminder_info = ""
                        if send_email_reminder or send_text_reminder:
                            reminder_info = " Patient will receive automated reminders."
                        response["guidance"] = f"Recall for '{recall_type}' scheduled successfully.{reminder_info} Use manageAppointments() to schedule the actual appointment when due."
                    return strip_empty_values(response)
                    
                case "update":
                    missing = [k for k, v in {
                        "record_id": record_id,
                        "recall_type": recall_type,
                        "notes": notes,
                    }.items() if not v]
                    if missing:
                        return {
                            "error": f"Missing required fields for update: {', '.join(missing)}",
                            "guidance": "Use action='list' first to get current recall values (patient_recall_id, recall_type, notes), then pass all required fields with your changes."
                        }

                    update_data: Dict[str, Any] = {
                        "recall_type": recall_type,
                        "notes": notes,
                    }
                    if recall_date:
                        update_data["recall_date"] = recall_date.isoformat()
                    if recall_time is not None:
                        update_data["recall_time"] = recall_time
                    if recall_timeunit:
                        update_data["recall_timeunit"] = recall_timeunit
                    if recall_period:
                        update_data["recall_period"] = recall_period
                    if provider_id:
                        update_data["provider_id"] = int(provider_id)
                    if send_email_reminder is not None:
                        update_data["send_email_reminder"] = send_email_reminder
                    if email_reminder_before is not None:
                        update_data["email_reminder_before"] = str(email_reminder_before)
                    if send_text_reminder is not None:
                        update_data["send_text_reminder"] = send_text_reminder
                    if text_reminder_before is not None:
                        update_data["text_reminder_before"] = str(text_reminder_before)

                    response = await client.put(f"/patients/{patient_id}/recalls/{record_id}", data=update_data)
                    if response.get("recalls"):
                        response["guidance"] = f"Recall {record_id} updated successfully. Updated reminder settings are now active."
                    return strip_empty_values(response)
                    
                case "delete":
                    if not record_id:
                        return {
                            "error": "record_id required for deletion",
                            "guidance": "Use action='list' to find the recall record_id first."
                        }
                    
                    response = await client.delete(f"/patients/{patient_id}/recalls/{record_id}")
                    if response.get("code") == "0":
                        response["guidance"] = f"Recall {record_id} deleted successfully. Patient will no longer receive reminders for this recall."
                    return strip_empty_values(response)
                    
        except Exception as e:
            logger.error(f"Error in managePatientRecalls: {e}")
            return {
                "error": str(e),
                "guidance": f"Recall {action} failed. Ensure patient_id is valid and provider/facility IDs exist. Use getPracticeInfo() to verify IDs."
            }

@clinical_support_mcp.tool
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
    
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient files and documents.

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
    # Extract user tokens and environment from HTTP headers (proper FastMCP way)
    access_token = None
    refresh_token = None
    base_url = None
    token_url = None
    
    try:
        headers = get_http_headers()
        access_token = headers.get('x-user-access-token')
        refresh_token = headers.get('x-user-refresh-token')
        base_url = headers.get('x-charmhealth-base-url')
        token_url = headers.get('x-charmhealth-token-url')
        client_secret = headers.get('x-charmhealth-client-secret')
        accounts_server = headers.get('x-charmhealth-accounts-server')
        
        # If accounts_server is provided, use it for token URL (mobile flow)
        if accounts_server:
            token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"
        
        # Normalize base URL to include API path
        if base_url and not base_url.endswith('/api/ehr/v1'):
            base_url = base_url.rstrip('/') + '/api/ehr/v1'
        
        if access_token:
            logger.info(f"managePatientFiles using user credentials")
        else:
            logger.info("managePatientFiles using environment variable credentials")
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
                    
                    return strip_empty_values(response)
                    
                case "delete_photo":
                    response = await client.delete(f"/patients/{patient_id}/photo")
                    
                    if response.get("code") == "0":
                        response["guidance"] = "Patient photo deleted successfully. The patient profile will no longer display a photo."
                    else:
                        response["guidance"] = "Photo deletion failed. Verify the patient has an existing photo to delete."
                    
                    return strip_empty_values(response)
                    
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
                    
                    return strip_empty_values(response)
                    
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
                    
                    return strip_empty_values(response)
                    
        except Exception as e:
            logger.error(f"Error in managePatientFiles: {e}")
            return {
                "error": str(e),
                "guidance": f"Patient file {action} failed. Check your file paths and parameters. Ensure files exist and are in supported formats."
            }

@clinical_support_mcp.tool
@with_tool_metrics()
async def managePatientLabs(
    action: Literal["list", "get_details"],
    # Common fields
    patient_id: Optional[str] = None,
    group_id: Optional[str] = None,
    lab_order_id: Optional[str] = None,
    
    # Listing fields
    reviewer_id: Optional[str] = None,
    status: Optional[int] = None,  # 0 or 2
    status_filter: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,
    start_index: Optional[int] = None,
    no_of_records: Optional[int] = None,
    sort_by: Optional[Literal["DATE", "FULL_NAME"]] = None,
    is_ascending: Optional[bool] = None,
    
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient laboratory results.
    
    <usecase>
    Laboratory results management - list lab results and get detailed reports.
    Lab results arrive automatically from integrated labs (LabCorp, Quest). For manual entry, use the CharmHealth web portal.
    </usecase>
    
    <instructions>
    Actions:
    - "list": Show lab results with filtering (optionally filter by patient_id, reviewer_id, status, date range)
    - "get_details": Get detailed lab report (requires group_id OR lab_order_id)
    For detailed results: Use group_id for result groups or lab_order_id for specific orders
    Status codes: 0 for pending, 2 for final results

    List filters (in addition to API parameters):
    - status_filter: 0 (pending) or 2 (final)
    - from_date / to_date: e.g., from_date="2025-01-01", to_date="2025-12-31" (best-effort against common date fields)
    - limit: e.g., limit=50

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.
    </instructions>
    """
    # Extract user tokens and environment from HTTP headers (proper FastMCP way)
    access_token = None
    refresh_token = None
    base_url = None
    token_url = None
    
    try:
        headers = get_http_headers()
        access_token = headers.get('x-user-access-token')
        refresh_token = headers.get('x-user-refresh-token')
        base_url = headers.get('x-charmhealth-base-url')
        token_url = headers.get('x-charmhealth-token-url')
        client_secret = headers.get('x-charmhealth-client-secret')
        accounts_server = headers.get('x-charmhealth-accounts-server')
        
        # If accounts_server is provided, use it for token URL (mobile flow)
        if accounts_server:
            token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"
        
        # Normalize base URL to include API path
        if base_url and not base_url.endswith('/api/ehr/v1'):
            base_url = base_url.rstrip('/') + '/api/ehr/v1'
        
        if access_token:
            logger.info(f"managePatientLabs using user credentials")
        else:
            logger.info("managePatientLabs using environment variable credentials")
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
                    params = {}
                    if reviewer_id:
                        params["reviewer_id"] = int(reviewer_id)
                    if patient_id:
                        params["patient_id"] = int(patient_id)
                    effective_status = status_filter if status_filter is not None else status
                    if effective_status is not None:
                        params["status"] = effective_status
                    if start_index:
                        params["start_index"] = start_index
                    if no_of_records:
                        params["no_of_records"] = no_of_records
                    if sort_by:
                        params["sort_by"] = sort_by
                    if is_ascending is not None:
                        params["is_ascending"] = is_ascending
                    
                    response = await client.get("/labs/results", params=params)

                    results = response.get("lab_results") or []
                    total_count = len(results)

                    wrappers = []
                    for r in results:
                        lab_date = (
                            (r or {}).get("date")
                            or (r or {}).get("result_date")
                            or (r or {}).get("collected_date")
                            or (r or {}).get("created_date")
                            or (r or {}).get("order_date")
                        )
                        wrappers.append({**(r or {}), "_orig": r, "lab_date": lab_date})

                    filtered_wrappers = wrappers
                    if from_date:
                        filtered_wrappers = filter_items(filtered_wrappers, {"lab_date": {"op": "gte", "value": from_date}})["items"]
                    if to_date:
                        filtered_wrappers = filter_items(filtered_wrappers, {"lab_date": {"op": "lte", "value": to_date}})["items"]

                    filtered_count = len(filtered_wrappers)
                    limited = filter_items(filtered_wrappers, filters=None, limit=limit)["items"] if limit is not None else filtered_wrappers

                    response["lab_results"] = [w.get("_orig", w) for w in limited]
                    response["total_count"] = total_count
                    response["filtered_count"] = filtered_count

                    if response.get("lab_results"):
                        result_count = len(response["lab_results"])
                        if patient_id:
                            response["guidance"] = f"Found {result_count} lab results for patient {patient_id}. If there is a group_id, use action='get_details' with group_id to see detailed results. Otherwise, use action='get_details' with lab_order_id to see detailed results."
                        else:
                            response["guidance"] = f"Found {result_count} lab results. Use action='get_details' to see specific result details or filter by patient_id."
                    else:
                        response["guidance"] = "No lab results found matching the criteria. Check your filter parameters or patient_id."
                    
                    return strip_empty_values(response)
                    
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
                    
                    return strip_empty_values(response)
                    
        except Exception as e:
            logger.error(f"Error in managePatientLabs: {e}")
            return {
                "error": str(e),
                "guidance": f"Lab {action} failed. Check your parameters and ensure IDs are valid. Use action='list' to find correct group_id or lab_order_id values."
            }
