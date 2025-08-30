from fastmcp import FastMCP
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals
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
    - "list": Show all patient notes (requires only patient_id)
    - "update": Modify existing note (requires record_id + notes content)
    - "delete": Remove note (requires record_id). Ask the user if they are sure they want to delete the note before proceeding.
    
    Use for: Important care instructions, provider alerts, patient preferences, social determinants
    Formal encounter notes should use manageEncounter() instead

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
                        response["guidance"] = f"Clinical note added successfully. This important information is now visible to all providers during patient care. For detailed encounter documentation, use manageEncounter()()."
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
                        guidance += ". These ensure timely preventive care and follow-up visits. Schedule appointments with manageAppointments() when recalls are due."
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
                        response["guidance"] = f"Recall for '{recall_type}' scheduled successfully.{reminder_info} Use manageAppointments() to schedule the actual appointment when due."
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

@clinical_support_mcp.tool
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
    Manage patient laboratory results.
    
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
