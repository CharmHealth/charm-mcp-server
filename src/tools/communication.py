from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, List, Dict, Any, Literal
from api import CharmHealthAPIClient
from common.utils import strip_empty_values
import logging
from telemetry import with_tool_metrics

logger = logging.getLogger(__name__)

communication_mcp = FastMCP(name="CharmHealth Communication MCP Server")


def _get_client_params() -> Dict[str, Any]:
    """Extract HTTP headers for API client initialization."""
    access_token = None
    refresh_token = None
    base_url = None
    token_url = None
    client_secret = None

    try:
        headers = get_http_headers()
        access_token = headers.get('x-user-access-token')
        refresh_token = headers.get('x-user-refresh-token')
        base_url = headers.get('x-charmhealth-base-url')
        token_url = headers.get('x-charmhealth-token-url')
        client_secret = headers.get('x-charmhealth-client-secret')
        accounts_server = headers.get('x-charmhealth-accounts-server')

        if accounts_server:
            token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"

        if base_url and not base_url.endswith('/api/ehr/v1'):
            base_url = base_url.rstrip('/') + '/api/ehr/v1'

        if access_token:
            logger.info("Communication tool using user credentials")
        else:
            logger.info("Communication tool using environment variable credentials")
    except Exception as e:
        logger.debug(f"Could not get HTTP headers (might be stdio mode): {e}")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "base_url": base_url,
        "token_url": token_url,
        "client_secret": client_secret,
    }


@communication_mcp.tool
@with_tool_metrics()
async def manageMessages(
    action: Literal["send", "list", "get_thread"],

    # Common
    patient_id: Optional[str] = None,
    facility_id: Optional[str] = None,

    # Send fields
    content: Optional[str] = None,
    channel: Optional[Literal["sms", "whatsapp", "secure", "auto"]] = "auto",
    subject: Optional[str] = None,  # For secure messages
    recipient_member_ids: Optional[str] = None,  # Comma-separated, for secure messages to providers
    template_name: Optional[str] = None,  # For WhatsApp templated messages
    template_header_placeholders: Optional[List[str]] = None,
    template_body_placeholders: Optional[List[str]] = None,

    # List fields
    message_type: Optional[Literal["incoming", "outgoing", "all"]] = "all",
    section: Optional[Literal["FROM_PATIENTS", "TO_PATIENTS", "ALL"]] = "ALL",
    page: Optional[int] = 1,
    page_size: Optional[int] = 20,

    # Get thread fields
    thread_channel: Optional[Literal["sms", "whatsapp", "secure", "all"]] = "all",

    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient and provider messaging across SMS, WhatsApp, and secure messaging channels.

    <usecase>
    Send messages to patients, read inbox messages, and retrieve conversation threads.
    Supports SMS (Twilio/Telnyx), WhatsApp Business, and secure portal messaging.
    Use this for patient communication, follow-ups, appointment confirmations, and
    responding to patient inquiries.
    </usecase>

    <instructions>
    Actions:
    - "send": Send a message to a patient (requires patient_id and content).
      Channel options:
        - "sms": Send via text message (patient must have TEXT_NOTIFY_ENABLED)
        - "whatsapp": Send via WhatsApp (patient must be opted in)
        - "secure": Send via secure portal message (requires subject)
        - "auto": Automatically select best available channel (default)
      For WhatsApp templates, provide template_name and placeholder values.
      For secure messages to providers, use recipient_member_ids.

    - "list": Show recent messages from inbox.
      Filter by section: "FROM_PATIENTS", "TO_PATIENTS", or "ALL".
      For SMS messages, filter by message_type: "incoming", "outgoing", or "all".
      Use facility_id to filter by facility.

    - "get_thread": Get full conversation history with a specific patient (requires patient_id).
      Filter by thread_channel to see only SMS, WhatsApp, secure, or all channels.

    Before sending clinical content, confirm with the provider. Routine messages
    (appointment reminders, general notifications) can be sent directly.
    </instructions>
    """
    client_params = _get_client_params()

    async with CharmHealthAPIClient(**client_params) as client:
        try:
            match action:
                case "send":
                    if not patient_id or not content:
                        return {
                            "error": "Missing required fields",
                            "guidance": "For sending, provide: patient_id and content. Optionally specify channel (sms/whatsapp/secure/auto)."
                        }

                    resolved_channel = channel or "auto"

                    if resolved_channel == "auto":
                        resolved_channel = await _resolve_channel(client, patient_id)

                    match resolved_channel:
                        case "sms":
                            return await _send_sms(client, patient_id, content, facility_id)
                        case "whatsapp":
                            return await _send_whatsapp(
                                client, patient_id, content, facility_id,
                                template_name, template_header_placeholders,
                                template_body_placeholders,
                            )
                        case "secure":
                            return await _send_secure_message(
                                client, patient_id, content, subject,
                                recipient_member_ids, facility_id,
                            )
                        case _:
                            return {
                                "error": f"Unknown channel: {resolved_channel}",
                                "guidance": "Use channel: sms, whatsapp, secure, or auto."
                            }

                case "list":
                    return await _list_messages(
                        client, section, message_type, facility_id,
                        page, page_size,
                    )

                case "get_thread":
                    if not patient_id:
                        return {
                            "error": "patient_id required for get_thread",
                            "guidance": "Provide patient_id to retrieve their conversation history."
                        }
                    return await _get_thread(
                        client, patient_id, thread_channel, page, page_size,
                    )

        except Exception as e:
            logger.error(f"Error in manageMessages: {e}")
            return {
                "error": str(e),
                "guidance": f"Message {action} failed. Check parameters and try again."
            }


async def _resolve_channel(client: CharmHealthAPIClient, patient_id: str) -> str:
    """Determine the best channel for a patient based on their preferences."""
    try:
        response = await client.get(f"/patients/{patient_id}/contactdetails")
        contact = response if isinstance(response, dict) else {}

        text_enabled = contact.get("text_notify_enabled", False)
        if isinstance(text_enabled, str):
            text_enabled = text_enabled.lower() == "true"

        whatsapp_enabled = contact.get("whatsapp_opted_in", False)
        if isinstance(whatsapp_enabled, str):
            whatsapp_enabled = whatsapp_enabled.lower() == "true"

        if whatsapp_enabled:
            return "whatsapp"
        if text_enabled:
            return "sms"
        return "secure"
    except Exception:
        return "secure"


async def _send_sms(
    client: CharmHealthAPIClient,
    patient_id: str,
    content: str,
    facility_id: Optional[str],
) -> Dict[str, Any]:
    """Send SMS to a patient."""
    data: Dict[str, Any] = {"content": content}
    if facility_id:
        data["facility_id"] = int(facility_id)

    response = await client.post(
        f"/textmessages/patient/{patient_id}/outgoing",
        data=data,
    )

    if response.get("error"):
        error_msg = str(response["error"]).lower()
        if "disabled" in error_msg or "preference" in error_msg:
            response["guidance"] = "Patient has text notifications disabled. Try channel='secure' for portal messaging."
        elif "10dlc" in error_msg or "registration" in error_msg:
            response["guidance"] = "Practice needs 10DLC registration for SMS. Try channel='secure' instead."
        else:
            response["guidance"] = "SMS send failed. Try channel='secure' as an alternative."
    else:
        response["channel_used"] = "sms"
        response["guidance"] = "SMS sent successfully."

    return strip_empty_values(response)


async def _send_whatsapp(
    client: CharmHealthAPIClient,
    patient_id: str,
    content: str,
    facility_id: Optional[str],
    template_name: Optional[str],
    header_placeholders: Optional[List[str]],
    body_placeholders: Optional[List[str]],
) -> Dict[str, Any]:
    """Send WhatsApp message to a patient."""
    data: Dict[str, Any] = {}

    if template_name:
        data["template_name"] = template_name
        template_content: Dict[str, Any] = {}
        if header_placeholders:
            template_content["HEADER_PLACEHOLDERS"] = header_placeholders
        if body_placeholders:
            template_content["BODY_PLACEHOLDERS"] = body_placeholders
        data["content"] = template_content
    else:
        data["freeform_content"] = content

    if facility_id:
        data["facility_id"] = int(facility_id)

    response = await client.post(
        f"/messages/whatsapp/patient/{patient_id}/send",
        data=data,
    )

    if response.get("error"):
        response["guidance"] = "WhatsApp send failed. Patient may not be opted in. Try channel='sms' or channel='secure'."
    else:
        response["channel_used"] = "whatsapp"
        response["guidance"] = "WhatsApp message sent successfully."

    return strip_empty_values(response)


async def _send_secure_message(
    client: CharmHealthAPIClient,
    patient_id: str,
    content: str,
    subject: Optional[str],
    recipient_member_ids: Optional[str],
    facility_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Send secure portal message."""
    data: Dict[str, Any] = {
        "content": content,
        "subject": subject or "Message from your care team",
        "patients": patient_id,
    }

    if facility_id:
        data["facility_id"] = int(facility_id)
    if recipient_member_ids:
        data["members"] = recipient_member_ids

    response = await client.post("/messages", data=data)

    if response.get("error"):
        response["guidance"] = "Secure message send failed. Verify patient has portal access."
    else:
        response["channel_used"] = "secure"
        response["guidance"] = "Secure message sent successfully. Patient will see it in their portal."

    return strip_empty_values(response)


async def _list_messages(
    client: CharmHealthAPIClient,
    section: Optional[str],
    message_type: Optional[str],
    facility_id: Optional[str],
    page: Optional[int],
    page_size: Optional[int],
) -> Dict[str, Any]:
    """List messages from inbox."""
    results: Dict[str, Any] = {"messages": []}

    # Fetch SMS messages
    sms_params: Dict[str, Any] = {"page": page or 1}
    if message_type and message_type != "all":
        sms_params["type"] = message_type.upper()
    else:
        sms_params["type"] = "BOTH"
    if facility_id:
        sms_params["facilityIds"] = facility_id

    sms_response = await client.get("/textmessages", params=sms_params)
    sms_messages = sms_response.get("messages", [])
    for msg in sms_messages:
        msg["channel"] = "sms"
    results["messages"].extend(sms_messages)

    # Fetch secure messages
    secure_params: Dict[str, Any] = {
        "startIndex": ((page or 1) - 1) * (page_size or 20) + 1,
        "noOfRecords": page_size or 20,
    }
    if section and section != "ALL":
        secure_params["section"] = section

    secure_response = await client.get("/messages", params=secure_params)
    secure_messages = secure_response.get("messages", [])
    for msg in secure_messages:
        msg["channel"] = "secure"
    results["messages"].extend(secure_messages)

    results["total_count"] = len(results["messages"])
    results["page"] = page or 1

    if results["messages"]:
        results["guidance"] = f"Found {results['total_count']} messages. Use action='get_thread' with a patient_id to see the full conversation."
    else:
        results["guidance"] = "No messages found matching the criteria."

    return strip_empty_values(results)


async def _get_thread(
    client: CharmHealthAPIClient,
    patient_id: str,
    channel: Optional[str],
    page: Optional[int],
    page_size: Optional[int],
) -> Dict[str, Any]:
    """Get full conversation thread with a patient."""
    results: Dict[str, Any] = {"messages": [], "patient_id": patient_id}

    include_sms = channel in ("sms", "all", None)
    include_whatsapp = channel in ("whatsapp", "all", None)
    include_secure = channel in ("secure", "all", None)

    if include_sms:
        sms_response = await client.get(
            f"/textmessages",
            params={"patient_id": patient_id, "type": "BOTH", "page": page or 1},
        )
        for msg in sms_response.get("messages", []):
            msg["channel"] = "sms"
            results["messages"].append(msg)

    if include_whatsapp:
        wa_response = await client.get(
            "/messages/whatsapp/fetch_patient_records",
            params={"patient_id": patient_id},
        )
        for msg in wa_response.get("messages", wa_response.get("records", [])):
            msg["channel"] = "whatsapp"
            results["messages"].append(msg)

    if include_secure:
        secure_response = await client.get(
            f"/messages/patient/{patient_id}",
            params={
                "startIndex": ((page or 1) - 1) * (page_size or 20) + 1,
                "noOfRecords": page_size or 20,
            },
        )
        for msg in secure_response.get("messages", []):
            msg["channel"] = "secure"
            results["messages"].append(msg)

    results["total_count"] = len(results["messages"])

    if results["messages"]:
        results["guidance"] = f"Found {results['total_count']} messages with this patient. Use action='send' to respond."
    else:
        results["guidance"] = "No message history found with this patient."

    return strip_empty_values(results)


@communication_mcp.tool
@with_tool_metrics()
async def manageFax(
    action: Literal["send", "status"],

    # Send fields
    recipient_fax_number: Optional[str] = None,
    recipient_name: Optional[str] = None,
    document_content_base64: Optional[str] = None,
    subject: Optional[str] = None,
    remarks: Optional[str] = None,
    facility_id: Optional[str] = None,
    reference: Optional[str] = None,

    # Status fields
    fax_id: Optional[str] = None,

    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Send faxes and check fax delivery status.

    <usecase>
    Fax clinical documents (referrals, records, prior auth forms) to providers,
    facilities, pharmacies, and insurance companies. Check delivery status of sent faxes.
    </usecase>

    <instructions>
    Actions:
    - "send": Fax a document (requires recipient_fax_number, recipient_name, document_content_base64).
      document_content_base64 must be a base64-encoded PDF.
      Optionally include subject, remarks, and reference for the cover page.
      facility_id determines which facility's fax credentials and return number are used.

    - "status": Check fax delivery status (requires fax_id).
      Status values: QUEUED, SENT, FAILED, YET_TO_SEND.

    Common fax use cases:
    - Referral letters to specialists
    - Medical records requests
    - Prior authorization forms to insurance
    - Prescription orders to pharmacies without e-prescribe
    </instructions>
    """
    client_params = _get_client_params()

    async with CharmHealthAPIClient(**client_params) as client:
        try:
            match action:
                case "send":
                    if not recipient_fax_number or not recipient_name or not document_content_base64:
                        return {
                            "error": "Missing required fields",
                            "guidance": "For sending a fax, provide: recipient_fax_number, recipient_name, and document_content_base64 (base64-encoded PDF)."
                        }

                    fax_data: Dict[str, Any] = {
                        "to_number": recipient_fax_number,
                        "recipient_name": recipient_name,
                        "document_content": document_content_base64,
                        "document_type": "PDF",
                    }

                    if subject:
                        fax_data["subject"] = subject
                    if remarks:
                        fax_data["remarks"] = remarks
                    if facility_id:
                        fax_data["facility_id"] = int(facility_id)
                    if reference:
                        fax_data["reference"] = reference

                    response = await client.post("/fax/send", data=fax_data)

                    if response.get("error"):
                        error_msg = str(response["error"]).lower()
                        if "not enabled" in error_msg or "disabled" in error_msg:
                            response["guidance"] = "Fax is not enabled for this facility. Check fax configuration."
                        else:
                            response["guidance"] = "Fax send failed. Verify the fax number format and facility configuration."
                    else:
                        fax_detail_id = response.get("FAXDETAILS_ID") or response.get("fax_id")
                        response["guidance"] = f"Fax queued for delivery (ID: {fax_detail_id}). Use action='status' to check delivery."

                    return strip_empty_values(response)

                case "status":
                    if not fax_id:
                        return {
                            "error": "fax_id required for status check",
                            "guidance": "Provide the fax_id returned from a previous send action."
                        }

                    response = await client.get(f"/fax/{fax_id}/status")

                    status = response.get("status", response.get("fax_status", "UNKNOWN"))
                    response["fax_id"] = fax_id
                    response["status"] = status

                    match status:
                        case "SENT":
                            response["guidance"] = "Fax delivered successfully."
                        case "QUEUED" | "YET_TO_SEND":
                            response["guidance"] = "Fax is still in the queue. Check again shortly."
                        case "FAILED":
                            response["guidance"] = "Fax delivery failed. Verify the fax number and try resending."
                        case _:
                            response["guidance"] = f"Fax status: {status}."

                    return strip_empty_values(response)

        except Exception as e:
            logger.error(f"Error in manageFax: {e}")
            return {
                "error": str(e),
                "guidance": f"Fax {action} failed. Check parameters and try again."
            }
