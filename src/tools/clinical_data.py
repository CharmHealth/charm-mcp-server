from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, List, Dict, Any, Literal, TypedDict, Union
from datetime import date
from pydantic import BaseModel, Field


class VitalEntry(BaseModel):
    """A single vital sign reading with name, value, and unit."""
    vital_name: str = Field(description="Exact CharmHealth vital name (e.g., 'Height', 'Weight', 'Systolic BP')")
    vital_value: str = Field(description="The vital value")
    vital_unit: str = Field(default="", description="Unit of measurement (e.g., 'ft', 'ins', 'lbs', 'mmHg')")
from api import CharmHealthAPIClient
from common.utils import build_params_from_locals, strip_empty_values
from common.filtering import filter_items
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
    
    # Vital signs data - can provide as dict, list of entries, or individual fields
    vitals: Optional[Union[Dict[str, str], List[VitalEntry]]] = None,
    
    # Individual vital fields
    vital_name: Optional[str] = None,
    vital_value: Optional[str] = None,
    vital_unit: Optional[str] = None,

    # List filters
    vital_name_filter: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,

    # Date for add without encounter
    entry_date: Optional[date] = None,

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
    - "add": Record new vitals (requires patient_id + vitals dict OR individual vital fields, plus encounter_id OR entry_date; defaults to today if neither provided). Check available vitals with getPracticeInfo(info_type='vitals') first to ensure all vital names and units are correct.
    - "list": Show patient vital history (optionally filter by vital name and/or date range)
    - "update": Modify existing vital record (requires record_id + fields to change)
    - "delete": Remove incorrect vital record (requires record_id)
    
    Vitals Format:
    - As dict: keys are EXACT CharmHealth vital names, values are "value unit" strings.
      Example: {"Systolic BP": "120 mmHg", "Diastolic BP": "80 mmHg", "Weight": "150 lbs", "Temp": "98 F"}
    - Individual: vital_name="Systolic BP", vital_value="120", vital_unit="mmHg"

    IMPORTANT: vital_name must be the exact CharmHealth API name. NEVER include units inside the name.
    Correct: "Systolic BP" | Wrong: "Systolic BP (mmHg)" or "Blood Pressure"
    Known names: Weight, Height, BMI, Temp, Systolic BP, Diastolic BP, Pulse Rate, Pulse Pattern, Pulse Volume, Vision
    Call getPracticeInfo(info_type='vitals') to get the full list of valid names and units for this practice.

    List filters:
    - vital_name_filter: e.g., vital_name_filter="Blood Pressure" (matches case-insensitively, substring ok)
    - from_date / to_date: e.g., from_date="2025-01-01", to_date="2025-12-31"
    - limit: e.g., limit=20

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
                    response = await client.get(f"/patients/{patient_id}/vitals", params={})

                    entries = response.get("vitals") or []
                    total_count = len(entries)

                    # Optionally filter inner vitals by name (and drop entries with no remaining vitals).
                    def _filter_entry_vitals(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                        if not vital_name_filter:
                            return entry

                        needle = str(vital_name_filter).casefold()
                        out = dict(entry)

                        if isinstance(out.get("vitals"), list):
                            vitals_list = []
                            for v in out.get("vitals", []):
                                name = str((v or {}).get("vital_name", "")).casefold()
                                if needle in name:
                                    vitals_list.append(v)
                            out["vitals"] = vitals_list
                            return out if vitals_list else None

                        if isinstance(out.get("vital_entries"), list):
                            new_entries = []
                            for ve in out.get("vital_entries", []):
                                ve_out = dict(ve or {})
                                if isinstance(ve_out.get("vitals"), list):
                                    ve_out["vitals"] = [
                                        v for v in ve_out.get("vitals", [])
                                        if needle in str((v or {}).get("vital_name", "")).casefold()
                                    ]
                                if ve_out.get("vitals"):
                                    new_entries.append(ve_out)
                            out["vital_entries"] = new_entries
                            return out if new_entries else None

                        # Unknown schema; keep entry unchanged.
                        return out

                    processed = []
                    for e in entries:
                        kept = _filter_entry_vitals(e)
                        if kept is not None:
                            processed.append(kept)

                    # Date filtering at entry level (best-effort across common keys)
                    wrappers: List[Dict[str, Any]] = []
                    for e in processed:
                        entry_date = (
                            e.get("entry_date")
                            or e.get("date")
                            or e.get("created_date")
                            or e.get("recorded_date")
                            or e.get("vital_date")
                        )
                        wrappers.append({**e, "_orig": e, "entry_date": entry_date})

                    first_pass = wrappers
                    if from_date:
                        first_pass = filter_items(first_pass, {"entry_date": {"op": "gte", "value": from_date}})["items"]
                    second_pass = first_pass
                    if to_date:
                        second_pass = filter_items(second_pass, {"entry_date": {"op": "lte", "value": to_date}})["items"]

                    # Apply limit after all filters
                    limited = filter_items(second_pass, filters=None, limit=limit)["items"] if limit is not None else second_pass

                    filtered_count = len(second_pass)
                    response["vitals"] = [w.get("_orig", w) for w in limited]
                    response["total_count"] = total_count
                    response["filtered_count"] = filtered_count

                    if response.get("vitals"):
                        response["guidance"] = (
                            f"Found {total_count} vital sign records; {filtered_count} match the provided filters."
                            " Use this data to track patient health trends and clinical progress."
                        )
                    else:
                        response["guidance"] = "No vital signs found matching the provided filters. Use action='add' to record vitals during encounters."

                    return strip_empty_values(response)
                    
                case "add":
                    vitals_list = []

                    if vitals:
                        if isinstance(vitals, list):
                            # List of VitalEntry — supports duplicate vital names (e.g., Height ft + ins)
                            vitals_list = [
                                {"vital_name": v.vital_name, "vital_value": v.vital_value, "vital_unit": v.vital_unit}
                                for v in vitals
                            ]
                        else:
                            # Dict format — parse "value unit" strings (legacy, no duplicate keys)
                            for vital_name_key, vital_value_with_unit in vitals.items():
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

                    # Build the vitals entry — link to encounter if provided, otherwise use entry_date (defaulting to today)
                    vitals_entry: Dict[str, Any] = {"vitals": vitals_list}
                    if encounter_id:
                        vitals_entry["encounter_id"] = encounter_id
                    else:
                        vitals_entry["entry_date"] = (entry_date or date.today()).isoformat()

                    response = await client.post(f"/patients/{patient_id}/vitals", data=[vitals_entry])

                    if response.get("vital_entries"):
                        recorded_vitals = [v["vital_name"] for v in vitals_list]
                        context_label = f"encounter {encounter_id}" if encounter_id else "today's visit"
                        response["guidance"] = f"Vitals recorded successfully: {', '.join(recorded_vitals)}. These are now part of the patient's clinical record for {context_label}."
                    else:
                        response["guidance"] = "Vitals recording failed. Verify vital names match practice standards. Use getPracticeInfo(info_type='vitals') for valid vital types."

                    return strip_empty_values(response)
                    
                case "update":
                    if not record_id:
                        return {
                            "error": "record_id required for updates",
                            "guidance": "Use action='list' to find the vital record_id first."
                        }
                    
                    # Build vitals list for update
                    vitals_list = []

                    if vitals:
                        if isinstance(vitals, list):
                            # List of VitalEntry — supports duplicate vital names
                            vitals_list = [
                                {"vital_name": v.vital_name, "vital_value": v.vital_value, "vital_unit": v.vital_unit}
                                for v in vitals
                            ]
                        else:
                            # Dict format — parse "value unit" strings (legacy)
                            for vital_name_key, vital_value_with_unit in vitals.items():
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
                    
                    if response.get("vital_entries"):
                        updated_vitals = [v["vital_name"] for v in vitals_list]
                        response["guidance"] = f"Vital record {record_id} updated successfully: {', '.join(updated_vitals)}. The corrected vital signs are now in the patient's record."
                    else:
                        response["guidance"] = "Vital update failed. Verify the record_id exists and the new values are valid."
                    
                    return strip_empty_values(response)
                
                    
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

    # List filters
    status_filter: Optional[Literal["active", "inactive"]] = None,
    limit: Optional[int] = None,
    
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
    - "update": Modify existing prescription (requires record_id + fields to change). IMPORTANT: drug name and strength CANNOT be changed via update — use discontinue + add instead. Updatable fields: directions, dispense, refills, status.
    - "discontinue": Stop drug (requires record_id)
    - "list": Show all patient drugs by type (filter by substance_type, optionally filter by status)
    
    Substance Types:
    - "medication": Prescription drugs (requires directions, refills)
    - "supplement": OTC supplements/vitamins (requires dosage as integer)
    - "vitamin": Specific vitamins (requires dosage as integer)
    
    Safety: Automatically checks allergies before prescribing unless check_allergies=False
    List filters:
    - status_filter: e.g., status_filter="active"
    - limit: e.g., limit=25
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
                            meds = response.get("medications", [])
                            total_count = len(meds)

                            wrappers = []
                            for m in meds:
                                derived_status = "active" if m.get("is_active") else "inactive"
                                wrappers.append({**(m or {}), "_orig": m, "status": derived_status})

                            filters: Dict[str, Any] = {}
                            if status_filter:
                                filters["status"] = status_filter

                            filtered = filter_items(wrappers, filters=filters or None, limit=limit)
                            response["medications"] = [w.get("_orig", w) for w in filtered["items"]]
                            response["total_count"] = total_count
                            response["filtered_count"] = filtered["filtered_count"]

                            active_meds = [med for med in response["medications"] if med.get("is_active")]
                            response["guidance"] = (
                                f"Patient has {total_count} total medications; {filtered['filtered_count']} match the provided filters"
                                f" ({len(active_meds)} active in returned list). Check managePatientAllergies() before prescribing new drugs."
                            )
                    else:
                        # Get supplements
                        response = await client.get(f"/patients/{patient_id}/supplements")
                        if response.get("supplements"):
                            supps = response.get("supplements", [])
                            total_count = len(supps)

                            wrappers = []
                            for s in supps:
                                derived_status = str((s or {}).get("status", "")).casefold()
                                wrappers.append({**(s or {}), "_orig": s, "status": derived_status})

                            filters: Dict[str, Any] = {}
                            if status_filter:
                                filters["status"] = str(status_filter).casefold()

                            filtered = filter_items(wrappers, filters=filters or None, limit=limit)
                            response["supplements"] = [w.get("_orig", w) for w in filtered["items"]]
                            response["total_count"] = total_count
                            response["filtered_count"] = filtered["filtered_count"]

                            active_supps = [s for s in response["supplements"] if str(s.get("status", "")).casefold() == "active"]
                            response["guidance"] = (
                                f"Patient has {total_count} total supplements/vitamins; {filtered['filtered_count']} match the provided filters"
                                f" ({len(active_supps)} active in returned list). Use action='add' to document new supplements."
                            )
                    
                    return strip_empty_values(response)
                    
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
                        if encounter_id:
                            med_data[0]["encounter_id"] = int(encounter_id)
                        if comments:
                            med_data[0]["comments"] = comments
                        
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
                    
                    return strip_empty_values(response)
                    
                case "update":
                    if not record_id:
                        return {
                            "error": "record_id required for updates",
                            "guidance": "Use action='list' to find the medication/supplement record_id first."
                        }

                    if substance_type == "medication":
                        # GET current record to preserve required fields the API mandates on every PUT
                        current_resp = await client.get(f"/patients/{patient_id}/medications")
                        current_meds = current_resp.get("medications", [])
                        current_med = next(
                            (m for m in current_meds if str(m.get("patient_medication_id")) == str(record_id)),
                            None,
                        )
                        if not current_med:
                            return {
                                "error": f"Medication record {record_id} not found",
                                "guidance": "Use action='list' to verify the record_id exists for this patient."
                            }

                        if drug_name or strength:
                            return {
                                "error": "Drug name and strength cannot be changed via update — these are catalog fields set at prescribing time.",
                                "guidance": "To change the drug or strength, use action='discontinue' on the current record, then action='add' to prescribe the new drug/strength."
                            }

                        # Build payload with all API-required fields, then overlay changes
                        # NOTE: PUT /medications/{id} only accepts: is_active, directions, dispense, refills,
                        # substitute_generic, manufacturing_type, and optional start_date/stop_date/dispense_unit/route/note_to_pharmacy
                        update_data: Dict[str, Any] = {
                            "is_active": current_med.get("is_active", True),
                            "directions": current_med.get("directions", ""),
                            "dispense": float(current_med.get("dispense") or 30),
                            "refills": str(current_med.get("refills", "0")),
                            "substitute_generic": current_med.get("substitute_generic", False),
                            "manufacturing_type": current_med.get("manufacturing_type", "Manufactured"),
                        }
                        _enc_id = current_med.get("encounter_id")
                        if _enc_id:
                            update_data["encounter_id"] = int(_enc_id)
                        if directions:
                            update_data["directions"] = directions
                        if refills:
                            update_data["refills"] = refills
                        if status:
                            update_data["is_active"] = status == "active"

                        response = await client.put(f"/patients/{patient_id}/medications/{record_id}", data=update_data)

                        if response.get("medications"):
                            response["guidance"] = f"Medication {record_id} updated successfully. Changes are now active in the patient's medication profile."
                    else:
                        # GET current supplement to carry supplement_name — API rejects the PUT without it
                        current_resp = await client.get(f"/patients/{patient_id}/supplements")
                        current_supps = current_resp.get("supplements", [])
                        current_supp = next(
                            (
                                s for s in current_supps
                                if str(s.get("supplement_id") or s.get("patient_supplement_id")) == str(record_id)
                            ),
                            None,
                        )
                        if not current_supp:
                            return {
                                "error": f"Supplement record {record_id} not found",
                                "guidance": "Use action='list' to verify the record_id exists for this patient."
                            }

                        update_data: Dict[str, Any] = {
                            "supplement_name": drug_name or current_supp.get("supplement_name", ""),
                        }
                        if dosage:
                            update_data["dosage"] = dosage
                        if strength:
                            update_data["strength"] = strength
                        if status:
                            update_data["status"] = status.title()
                        if frequency:
                            update_data["frequency"] = frequency
                        if comments:
                            update_data["comments"] = comments
                        elif directions:
                            update_data["comments"] = directions

                        response = await client.put(f"/patients/{patient_id}/supplements/{record_id}", data=update_data)
                        
                        if response.get("supplements"):
                            response["guidance"] = f"Supplement {record_id} updated successfully. Changes are reflected in the patient's supplement list."
                    
                    return strip_empty_values(response)
                    
                case "discontinue":
                    if not record_id:
                        return {
                            "error": "record_id required to discontinue drug",
                            "guidance": "Use action='list' to find the medication/supplement record_id first."
                        }

                    if substance_type == "medication":
                        # GET current record to preserve required fields the API mandates on every PUT
                        current_resp = await client.get(f"/patients/{patient_id}/medications")
                        current_meds = current_resp.get("medications", [])
                        current_med = next(
                            (m for m in current_meds if str(m.get("patient_medication_id")) == str(record_id)),
                            None,
                        )
                        if not current_med:
                            return {
                                "error": f"Medication record {record_id} not found",
                                "guidance": "Use action='list' to verify the record_id exists for this patient."
                            }

                        discontinue_data: Dict[str, Any] = {
                            "is_active": False,
                            "directions": current_med.get("directions", ""),
                            "dispense": float(current_med.get("dispense") or 30),
                            "refills": str(current_med.get("refills", "0")),
                            "substitute_generic": current_med.get("substitute_generic", False),
                            "manufacturing_type": current_med.get("manufacturing_type", "Manufactured"),
                        }
                        _enc_id = current_med.get("encounter_id")
                        if _enc_id:
                            discontinue_data["encounter_id"] = int(_enc_id)
                        response = await client.put(f"/patients/{patient_id}/medications/{record_id}", data=discontinue_data)

                        if response.get("medications"):
                            response["guidance"] = f"Medication {record_id} discontinued. Patient should stop taking this medication. Document discontinuation reason in next encounter with manageEncounter()."
                    else:
                        # GET current supplement to carry supplement_name — API rejects the PUT without it
                        current_resp = await client.get(f"/patients/{patient_id}/supplements")
                        current_supps = current_resp.get("supplements", [])
                        current_supp = next(
                            (
                                s for s in current_supps
                                if str(s.get("supplement_id") or s.get("patient_supplement_id")) == str(record_id)
                            ),
                            None,
                        )
                        if not current_supp:
                            return {
                                "error": f"Supplement record {record_id} not found",
                                "guidance": "Use action='list' to verify the record_id exists for this patient."
                            }

                        response = await client.put(
                            f"/patients/{patient_id}/supplements/{record_id}",
                            data={
                                "supplement_name": current_supp.get("supplement_name", ""),
                                "status": "Inactive",
                            },
                        )

                        if response.get("supplements"):
                            response["guidance"] = f"Supplement {record_id} discontinued. This supplement is no longer part of the patient's active regimen."
                    
                    return strip_empty_values(response)
                
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

    # List filters
    severity_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    limit: Optional[int] = None,
    
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
    - "list": Show all patient allergies (optionally filter by severity/type)
    - "update": Modify existing allergy (requires record_id, allergen, allergy_type, severity, allergy_status — use action='list' first to get current values, then pass all required fields with your changes)
    - "delete": Remove allergy record (requires record_id)
    
    Safety critical: Always check allergies before prescribing medications.
    Common allergens: "Penicillin", "Latex", "Shellfish", "Nuts", "Contrast dye"
    Severity levels: "Mild", "Moderate", "Severe"
    Allergy types: "Medication", "Drug Substance", "Environmental", "Food", "Plant", "Animal", "Latex"
    Status values: "Active", "Inactive"

    List filters:
    - severity_filter: e.g., severity_filter="Severe"
    - type_filter: e.g., type_filter="Drug"
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
                        allergies = response.get("allergies", [])
                        total_count = len(allergies)

                        wrappers = []
                        for a in allergies:
                            wrappers.append({
                                **(a or {}),
                                "_orig": a,
                                "allergy_type": (a or {}).get("allergy_type") or (a or {}).get("type"),
                            })

                        filters: Dict[str, Any] = {}
                        if severity_filter:
                            filters["severity"] = severity_filter
                        if type_filter:
                            filters["allergy_type"] = type_filter

                        filtered = filter_items(wrappers, filters=filters or None, limit=limit)
                        response["allergies"] = [w.get("_orig", w) for w in filtered["items"]]
                        response["total_count"] = total_count
                        response["filtered_count"] = filtered["filtered_count"]

                        allergy_count = len(response["allergies"])
                        severe_allergies = [a for a in response["allergies"] if str(a.get("severity", "")).lower() in ["severe", "life-threatening"]]
                        
                        guidance = f"Patient has {allergy_count} documented allergies"
                        if severe_allergies:
                            guidance += f", including {len(severe_allergies)} severe/life-threatening allergies"
                        guidance += ". CRITICAL: Review all allergies before prescribing with manageMedications() or managePatientDrugs()."
                        response["guidance"] = guidance
                    else:
                        response["guidance"] = "No allergies documented. Before prescribing medications, confirm with patient if they have any known allergies."
                    return strip_empty_values(response)
                    
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
                    return strip_empty_values(response)
                    
                case "update":
                    missing = [k for k, v in {
                        "record_id": record_id,
                        "allergen": allergen,
                        "allergy_type": allergy_type,
                        "severity": severity,
                        "allergy_status": allergy_status,
                        "allergy_date": allergy_date,
                    }.items() if v is None or v == ""] + (
                        ["reactions"] if reactions is None else []
                    )
                    if missing:
                        return {
                            "error": f"Missing required fields for update: {', '.join(missing)}",
                            "guidance": "Use action='list' first to get current allergy values, then pass all required fields: record_id, allergen, allergy_type, severity, allergy_status, reactions (pass empty string if no reactions), allergy_date (observed_on from list)."
                        }

                    update_data = {
                        "allergen": allergen,
                        "type": allergy_type,
                        "severity": severity,
                        "status": allergy_status,
                        "reactions": reactions,
                        "date": allergy_date.isoformat(),
                    }

                    response = await client.put(f"/patients/{patient_id}/allergies/{record_id}", data=update_data)
                    if response.get("patient_allergy"):
                        response["guidance"] = f"Allergy record {record_id} updated successfully. Updated allergy information is now active in safety alerts."
                    return strip_empty_values(response)
                    
                case "delete":
                    if not record_id:
                        return {
                            "error": "record_id required for deletion",
                            "guidance": "Use action='list' to find the allergy record_id first."
                        }
                    
                    response = await client.delete(f"/patients/{patient_id}/allergies/{record_id}")
                    if response.get("code") == "0":
                        response["guidance"] = f"Allergy record {record_id} deleted successfully. This allergy will no longer appear in clinical alerts. Ensure this is correct before prescribing."
                    return strip_empty_values(response)
                    
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

    # List filters (optional)
    status_filter: Optional[str] = None,
    code_type_filter: Optional[str] = None,
    limit: Optional[int] = None,
    
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
    - "list": Show all patient diagnoses (optionally filter by status, code type, and/or date range)
    - "update": Modify existing diagnosis (requires record_id + fields to change)
    - "delete": Remove diagnosis (requires record_id). Ask the user if they are sure they want to delete the diagnosis before proceeding.
    
    Code types: "ICD10", "SNOMED"
    Status options: "Active", "Inactive", "Resolved"
    List filters:
    - status_filter: filter by diagnosis_status (e.g., status_filter="Active")
    - code_type_filter: filter by code_type (e.g., code_type_filter="ICD10")
    - from_date / to_date: best-effort date filtering (e.g., from_date="2025-01-01", to_date="2025-12-31")
    - limit: e.g., limit=25
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
                    diagnoses = response.get("diagnoses") or response.get("patient_diagnoses") or []
                    total_count = len(diagnoses)

                    wrappers = []
                    for d in diagnoses:
                        status_val = (d or {}).get("diagnosis_status") or (d or {}).get("status")
                        code_val = (d or {}).get("code_type") or (d or {}).get("codeType")
                        dx_date = (d or {}).get("from_date") or (d or {}).get("date") or (d or {}).get("created_date") or (d or {}).get("to_date")
                        wrappers.append({
                            **(d or {}),
                            "_orig": d,
                            "diagnosis_status": status_val,
                            "code_type": code_val,
                            "diagnosis_date": dx_date,
                        })

                    filters: Dict[str, Any] = {}
                    if status_filter:
                        filters["diagnosis_status"] = status_filter
                    if code_type_filter:
                        filters["code_type"] = code_type_filter

                    filtered_wrappers = wrappers
                    if filters:
                        filtered_wrappers = filter_items(filtered_wrappers, filters=filters)["items"]
                    if from_date:
                        filtered_wrappers = filter_items(filtered_wrappers, filters={"diagnosis_date": {"op": "gte", "value": from_date}})["items"]
                    if to_date:
                        filtered_wrappers = filter_items(filtered_wrappers, filters={"diagnosis_date": {"op": "lte", "value": to_date}})["items"]

                    filtered_count = len(filtered_wrappers)
                    limited_wrappers = filter_items(filtered_wrappers, filters=None, limit=limit)["items"] if limit is not None else filtered_wrappers

                    response["diagnoses"] = [w.get("_orig", w) for w in limited_wrappers]
                    response["total_count"] = total_count
                    response["filtered_count"] = filtered_count

                    if response.get("diagnoses"):
                        active_dx = [d for d in response["diagnoses"] if str(d.get("status") or d.get("diagnosis_status") or "").lower() == "active"]
                        guidance = f"Patient has {total_count} documented diagnoses; {filtered_count} match the provided filters ({len(active_dx)} active in returned list)"
                        if encounter_id:
                            guidance += f" (API filtered by encounter {encounter_id})"
                        guidance += ". Use manageMedications() or managePatientDrugs() to prescribe treatments for active diagnoses."
                        response["guidance"] = guidance
                    else:
                        response["guidance"] = "No diagnoses found matching the provided filters. Use action='add' to document patient conditions for proper care planning."

                    return strip_empty_values(response)
                    
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
                    return strip_empty_values(response)
                    
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
                    return strip_empty_values(response)
                    
                case "delete":
                    if not record_id:
                        return {
                            "error": "record_id required for deletion",
                            "guidance": "Use action='list' to find the diagnosis record_id first."
                        }
                    
                    response = await client.delete(f"/patients/{patient_id}/diagnoses/{record_id}")
                    if response.get("code") == "0":
                        response["guidance"] = f"Diagnosis {record_id} removed from problem list. Ensure this doesn't affect ongoing treatment plans."
                    return strip_empty_values(response)
                    
        except Exception as e:
            logger.error(f"Error in managePatientDiagnoses: {e}")
            return {
                "error": str(e),
                "guidance": f"Diagnosis {action} failed. Accurate diagnosis documentation is essential for proper patient care and billing."
            }
