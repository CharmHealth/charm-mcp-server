from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

encounter_management_mcp = FastMCP(name="CharmHealth Encounter Management MCP Server")

@encounter_management_mcp.tool
@with_tool_metrics()
async def manageEncounter(
    patient_id: str,
    action: Literal["create", "review", "sign", "unlock", "update"] = "create",
    provider_id: Optional[str] = None,
    facility_id: Optional[str] = None,
    encounter_date: Optional[date] = None,
    encounter_id: Optional[str] = None,  # Required for review/sign/unlock actions
    appointment_id: Optional[str] = None,
    visit_type_id: Optional[str] = None,
    encounter_mode: Optional[Literal["In Person", "Phone Call", "Video Consult"]] = "In Person",
    chief_complaint: Optional[str] = None,
    reason: Optional[str] = None,  # Required for unlock action
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage encounters.
    
    <usecase>
    Complete encounter workflow - create, review, and sign encounters with comprehensive clinical documentation.
    Essential for clinical workflow from initial documentation through final signature.
    </usecase>
    
    <instructions>
    Actions:
    - "create": Create new encounter and document clinical findings (default)
    - "review": Display complete encounter details for review before signing
    - "sign": Electronically sign encounter after review and confirmation
    - "unlock": Unlock a previously signed encounter to allow modifications
    
    For creating encounters:
    - Requires: patient_id, provider_id, facility_id, encounter_date
    - Optional: appointment_id (to create from existing appointment), visit_type_id, encounter_mode, chief_complaint
    
    For reviewing encounters:
    - Requires: patient_id, encounter_id
    - Shows comprehensive encounter details including vitals, diagnoses, medications, notes
    
    For signing encounters:
    - Requires: patient_id, encounter_id  
    - Only use after reviewing and confirming all information is accurate
    
    For unlocking encounters:
    - Requires: patient_id, encounter_id, reason
    - Used to unlock signed encounters when modifications are needed
    - Must provide a valid reason for unlocking the encounter
    
    Recommended workflow:
    1. Create encounter: manageEncounter(patient_id, provider_id, facility_id, encounter_date, action="create")
    2. Add clinical data using managePatientVitals(), managePatientDrugs(), managePatientDiagnoses()
    3. Review before signing: manageEncounter(patient_id, encounter_id, action="review")
    4. Sign to finalize: manageEncounter(patient_id, encounter_id, action="sign")
    5. If modifications needed: manageEncounter(patient_id, encounter_id, reason="reason for changes", action="unlock")
    
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
            logger.info(f"manageEncounter using user credentials")
        else:
            logger.info("manageEncounter using environment variable credentials")
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
                case "review":
                    if not encounter_id:
                        return {
                            "error": "encounter_id required for review",
                            "guidance": "To review an encounter, provide the encounter_id. Use action='create' to create a new encounter."
                        }
                    
                    # Get comprehensive encounter details
                    encounter_details = {}
                    
                    # Get basic encounter info
                    encounter_response = await client.get("/encounters", params={
                        "patient_id": patient_id
                    })
                    for encounter in encounter_response.get("encounters", []):
                        if encounter.get("encounter_id") == encounter_id:
                            encounter = encounter
                            break
                    else:
                        return {
                            "error": "Encounter not found",
                            "guidance": f"No encounter found with ID {encounter_id} for patient {patient_id}. Verify the encounter_id is correct."
                        }
                    
                    
                    encounter_details["encounter_info"] = {
                        "encounter_id": encounter.get("encounter_id"),
                        "encounter_date": encounter.get("encounter_date"),
                        "provider": encounter.get("provider_name"),
                        "facility": encounter.get("facility_name"),
                        "encounter_mode": encounter.get("encounter_mode"),
                        "visit_type": encounter.get("visit_type"),
                        "status": encounter.get("status")
                    }
                    
                    # Get patient demographics for context
                    patient_response = await client.get(f"/patients/{patient_id}")
                    if patient_response.get("patient"):
                        patient = patient_response["patient"]
                        encounter_details["patient_info"] = {
                            "name": f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip(),
                            "dob": patient.get("date_of_birth"),
                            "gender": patient.get("gender"),
                            "record_id": patient.get("record_id")
                        }
                    
                    # Get vitals for this encounter
                    try:
                        vitals_response = await client.get(f"/patients/{patient_id}/vitals", params={
                            "encounter_id": encounter_id
                        })
                        encounter_details["vitals"] = vitals_response.get("vitals", [])
                    except:
                        encounter_details["vitals"] = []
                    
                    # Get diagnoses for this encounter
                    try:
                        diagnoses_response = await client.get(f"/patients/{patient_id}/diagnoses", params={
                            "encounter_id": encounter_id
                        })
                        encounter_details["diagnoses"] = diagnoses_response.get("diagnoses", [])
                    except:
                        encounter_details["diagnoses"] = []
                    
                    # Get medications for this encounter
                    try:
                        medications_response = await client.get(f"/patients/{patient_id}/medications", params={
                            "encounter_id": encounter_id
                        })
                        encounter_details["medications"] = medications_response.get("medications", [])
                    except:
                        encounter_details["medications"] = []
                    
                    # Get clinical notes from encounter
                    clinical_notes = encounter.get("clinical_notes") or encounter.get("chief_complaints")
                    if clinical_notes:
                        encounter_details["clinical_notes"] = clinical_notes
                    
                    # Create summary for review
                    summary_items = []
                    if encounter_details["vitals"]:
                        summary_items.append(f"✓ {len(encounter_details['vitals'])} vital sign(s) recorded")
                    if encounter_details["diagnoses"]:
                        summary_items.append(f"✓ {len(encounter_details['diagnoses'])} diagnosis/diagnoses documented")
                    if encounter_details["medications"]:
                        summary_items.append(f"✓ {len(encounter_details['medications'])} medication(s) prescribed/reviewed")
                    if encounter_details.get("clinical_notes"):
                        summary_items.append("✓ Clinical notes documented")
                    
                    # Check if already signed
                    is_signed = encounter.get("status") == "signed"
                    
                    return {
                        "action": "review",
                        "encounter_details": encounter_details,
                        "summary": summary_items,
                        "is_signed": is_signed,
                        "ready_to_sign": len(summary_items) > 0 and not is_signed,
                        "guidance": f"""
    ENCOUNTER REVIEW - Please confirm all information is accurate:

    Patient: {encounter_details.get('patient_info', {}).get('name', 'Unknown')} ({encounter_details.get('patient_info', {}).get('record_id', 'No ID')})
    Date: {encounter_details['encounter_info']['encounter_date']}
    Provider: {encounter_details['encounter_info']['provider']}
    Facility: {encounter_details['encounter_info']['facility']}
    Status: {encounter_details['encounter_info']['status']}

    Documentation Summary:
    {chr(10).join(summary_items) if summary_items else 'WARNING: No clinical documentation found'}

    {'SIGNED: This encounter is already signed.' if is_signed else f'''
    IMPORTANT: Review all details above carefully. Once signed, this encounter becomes legally binding and cannot be modified.

    To sign after review: manageEncounter(patient_id='{patient_id}', encounter_id='{encounter_id}', action='sign')''' if summary_items else '''
    WARNING: This encounter has minimal documentation. Consider adding vitals, diagnoses, or medications before signing.

    To add documentation:
    - managePatientVitals(patient_id='{patient_id}', encounter_id='{encounter_id}', action='add')
    - managePatientDiagnoses(patient_id='{patient_id}', encounter_id='{encounter_id}', action='add')
    - managePatientDrugs(patient_id='{patient_id}', encounter_id='{encounter_id}', action='add')'''}
    """
                    }
            
                case "sign":
                    if not encounter_id:
                        return {
                            "error": "encounter_id required for signing",
                            "guidance": "To sign an encounter, provide the encounter_id. Use action='review' first to confirm all details."
                        }
                    
                    # First verify encounter exists and get current status
                    encounter_response = await client.get(f"/soap/encounters/{encounter_id}")
                    
                    encounter = encounter_response.get("soap_encounter", {})
                    if not encounter:
                        return {
                            "error": "Encounter not found", 
                            "guidance": f"Cannot sign - encounter {encounter_id} not found for patient {patient_id} or encounter is already signed."
                        }
                    
                    # Attempt to sign
                    sign_response = await client.post(
                        f"/patients/{patient_id}/encounters/{encounter_id}/sign"
                    )
                    
                    if sign_response.get("code") == "0":
                        return {
                            "action": "sign",
                            "encounter_id": encounter_id,
                            "signed": True,
                            "message": sign_response.get("message", "Encounter signed successfully"),
                            "signed_encounter": sign_response.get("encounter", {}),
                            "guidance": "Encounter signed successfully! The encounter is now finalized and legally binding. No further modifications can be made unless you unlock the encounter."
                        }
                    else:
                        return {
                            "action": "sign",
                            "encounter_id": encounter_id,
                            "signed": False,
                            "error": f"Failed to sign encounter: {sign_response.get('message', 'Unknown error')}",
                            "guidance": "Signing failed. Verify you have permission to sign this encounter and that all required documentation is complete. Use action='review' to check encounter details."
                        }
                
                case "unlock":
                    if not encounter_id:
                        return {
                            "error": "encounter_id required for unlocking",
                            "guidance": "To unlock an encounter, provide the encounter_id. Use action='review' first to verify encounter status."
                        }
                    
                    if not reason:
                        return {
                            "error": "reason required for unlocking",
                            "guidance": "To unlock an encounter, provide a reason explaining why the signed encounter needs to be unlocked for modification."
                        }
                    
                    # Unlock the encounter using the API
                    unlock_data = {"reason": reason}
                    unlock_response = await client.post(
                        f"/api/ehr/v1/encounters/{encounter_id}/unlock",
                        data=unlock_data
                    )
                    
                    if unlock_response.get("code") == "0":
                        return {
                            "action": "unlock",
                            "encounter_id": encounter_id,
                            "unlocked": True,
                            "message": unlock_response.get("message", "Chart note unlocked successfully"),
                            "reason": reason,
                            "guidance": "Encounter unlocked successfully! The signed encounter can now be modified. Remember to sign it again after making necessary changes using action='sign'."
                        }
                    else:
                        return {
                            "action": "unlock",
                            "encounter_id": encounter_id,
                            "unlocked": False,
                            "error": f"Failed to unlock encounter: {unlock_response.get('message', 'Unknown error')}",
                            "reason": reason,
                            "guidance": "Unlocking failed. Verify you have permission to unlock this encounter and that it is currently signed. Only signed encounters can be unlocked."
                        }
                
            
                case "create":
                    if not provider_id or not facility_id or not encounter_date:
                        return {
                            "error": "Missing required parameters for encounter creation",
                            "guidance": "To create an encounter, provide: patient_id, provider_id, facility_id, encounter_date. Use action='review' or 'sign' for existing encounters."
                        }
                        
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
                        "action": "create",
                        "encounter_id": encounter_id,
                        "documentation_completed": documentation_steps,
                        "guidance": f"""Encounter created successfully (ID: {encounter_id})! 

    Next steps:
    1. Add clinical documentation:
    - managePatientVitals(patient_id='{patient_id}', encounter_id='{encounter_id}', action='add') 
    - managePatientDiagnoses(patient_id='{patient_id}', encounter_id='{encounter_id}', action='add')
    - managePatientDrugs(patient_id='{patient_id}', encounter_id='{encounter_id}', action='add')

    2. Review before signing:
    - manageEncounter(patient_id='{patient_id}', encounter_id='{encounter_id}', action='review')

    3. Sign when complete:
    - manageEncounter(patient_id='{patient_id}', encounter_id='{encounter_id}', action='sign')"""
                    }
                    return result
                
                case "update":
                    if not encounter_id:
                        return {
                            "error": "encounter_id required for updating",
                            "guidance": "To update an encounter, provide the encounter_id. Use action='review' first to verify encounter status."
                        }
                    
                    # Update the encounter
                    update_data = {}
                    if chief_complaint:
                        update_data["chief_complaints"] = chief_complaint
                    update_response = await client.post(f"/soap/encounters/{encounter_id}", data=update_data)
                    if update_response.get("code") == "0":
                        return {
                            "action": "update",
                            "encounter_id": encounter_id,
                            "updated": True,
                            "message": "Encounter updated successfully",
                            "guidance": "Encounter updated successfully! The encounter is now updated."
                        }
                    else:
                        return {
                            "error": "Failed to update encounter",
                            "guidance": "Check that patient_id and encounter_id are correct. If using appointment_id, verify the appointment exists and hasn't been converted to an encounter already."
                        }
            
        except Exception as e:
            logger.error(f"Error in manageEncounter: {e}")
            return {
                "error": str(e),
                "guidance": f"Failed to {action} encounter. Verify patient_id and encounter_id are correct and you have appropriate permissions."
            }
