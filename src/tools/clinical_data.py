from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, List, Dict, Any, Literal, TypedDict
from datetime import date
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

clinical_data_mcp = FastMCP(name="CharmHealth Clinical Data MCP Server")

@clinical_data_mcp.tool
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
    limit: Optional[int] = None,
    
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient vitals and vital signs.

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
            logger.info(f"managePatientVitals using user credentials")
        else:
            logger.info("managePatientVitals using environment variable credentials")
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
                            "guidance": "Vitals must be linked to an encounter. Use manageEncounter()() first to create an encounter, then record vitals."
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

@clinical_data_mcp.tool
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
    
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient drugs and supplements.

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
            logger.info(f"managePatientDrugs using user credentials")
        else:
            logger.info("managePatientDrugs using environment variable credentials")
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
            # Safety check: Review allergies before prescribing
            if action == "add" and check_allergies:
                allergy_response = await client.get(f"/patients/{patient_id}/allergies")
                if allergy_response.get("allergies"):
                    allergies = allergy_response["allergies"]
                    if allergies and substance_type == "medication":
                        allergy_warning = f"WARNING: Patient has {len(allergies)} documented allergies. Review before prescribing: "
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
                            response["guidance"] = f"Medication {record_id} discontinued. Patient should stop taking this medication. Document discontinuation reason in next encounter with manageEncounter()()."
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

@clinical_data_mcp.tool
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
    
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient allergies.

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
            logger.info(f"managePatientAllergies using user credentials")
        else:
            logger.info("managePatientAllergies using environment variable credentials")
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
                            severity_warning = "SEVERE ALLERGY ALERT: This will trigger warnings during prescribing."
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

@clinical_data_mcp.tool
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
    
    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient diagnoses.
    
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
            logger.info(f"managePatientDiagnoses using user credentials")
        else:
            logger.info("managePatientDiagnoses using environment variable credentials")
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
                        guidance += " Consider appropriate treatments (medications, supplements, etc.) with managePatientDrugs() or schedule follow-up with manageAppointments()."
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
