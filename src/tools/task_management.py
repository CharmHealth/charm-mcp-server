from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, Dict, Any, Literal, List
from datetime import date
import logging

from api import CharmHealthAPIClient
from common.utils import build_params_from_locals, strip_empty_values
from common.filtering import filter_items
from telemetry import with_tool_metrics

logger = logging.getLogger(__name__)

task_management_mcp = FastMCP(name="CharmHealth Task Management MCP Server")


@task_management_mcp.tool
@with_tool_metrics()
async def manageTasks(
    action: Literal["add", "update", "list", "change_status"],

    # Identifiers
    task_id: Optional[str] = None,
    patient_id: Optional[str] = None,

    # Task fields (add/update)
    task: Optional[str] = None,
    owner_id: Optional[str] = None,
    priority: Optional[Literal["0", "1", "2", "3"]] = None,
    status: Optional[str] = None,  # Pending | In-progress | Completed (also used as list filter)
    comments: Optional[str] = None,
    due_date: Optional[date] = None,
    reminder_options: Optional[str] = None,  # "On Due Date,3 Days Before"
    tasklist: Optional[str] = None,

    # List filters
    view: Optional[Literal["All", "MyTasks", "AssignedToMe", "AssignedByMe"]] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    page: Optional[int] = None,
    per_page: Optional[int] = None,

    # Additional list filters (applied client-side after fetching)
    status_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    owner_filter: Optional[str] = None,
    limit: Optional[int] = None,

    # Bulk ops (delete/print)
    task_ids: Optional[List[int]] = None,

    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage CharmHealth tasks.

    <usecase>
    Task management with task creation, updating, and listing.
    </usecase>

    <instructions>
    Actions:
    - "add": Create new task (requires task, owner_id (look up members using getPracticeInfo()), priority (0-Low, 1-Medium, 2-High, 3-Critical), status (Pending, In-progress, Completed), comments, due_date, reminder_options, tasklist. optional: patient_id if task is related to a patient)
    - "update": Modify existing task (requires task_id, task, owner_id, priority, status, tasklist — use manageTasks(action='list') first to get current values, then pass all required fields with your changes)
    - "list": Show tasks with filtering (supports view/date range/pagination plus client-side filters)
    - "change_status": Change the status of a task (requires task_id (use manageTasks(action='list') to get task_id) + new_status (Pending, In-progress, Completed))

    When required parameters are missing, ask the user to provide the specific values rather than proceeding with defaults or auto-generated values.

    List filters:
    - status_filter: filter by status (e.g., status_filter="Pending")
    - priority_filter: "0"-"3" or "Low"/"Medium"/"High"/"Critical"
    - owner_filter: filter by owner_id
    - limit: max tasks to return (applied after filtering)

    Examples:
    - manageTasks(action="list", view="MyTasks", status_filter="In-progress", limit=20)
    - manageTasks(action="list", view="All", priority_filter="High", owner_filter="12345")
    </instructions>
    """
    # Extract user tokens and environment from HTTP headers
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
        if base_url and not base_url.endswith('/api/ehr/v1'):
            base_url = base_url.rstrip('/') + '/api/ehr/v1'
        if access_token:
            logger.info(f"manageTasks using user credentials")
        else:
            logger.info("manageTasks using environment variable credentials")
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
                case "add":
                    missing = [k for k, v in {
                        "task": task,
                        "owner_id": owner_id,
                        "priority": priority,
                        "status": status,
                        "tasklist": tasklist,
                    }.items() if not v]
                    if missing:
                        return {"error": f"Missing required fields for add: {', '.join(missing)}"}

                    task_data = {
                        "task": task,
                        "owner_id": owner_id,
                        "priority": priority,
                        "status": status,
                        "tasklist": tasklist,
                    }
                    # optional fields
                    if patient_id:
                        task_data["patient_id"] = patient_id
                    if comments:
                        task_data["comments"] = comments
                    if due_date:
                        task_data["due_date"] = due_date.isoformat()
                    if reminder_options:
                        task_data["reminder_options"] = reminder_options

                    return strip_empty_values(await client.post("/tasks", data=task_data))

                case "update":
                    missing = [k for k, v in {
                        "task_id": task_id,
                        "task": task,
                        "owner_id": owner_id,
                        "priority": priority,
                        "status": status,
                        "tasklist": tasklist,
                    }.items() if not v]
                    if missing:
                        return {
                            "error": f"Missing required fields for update: {', '.join(missing)}",
                            "guidance": "Use manageTasks(action='list') first to retrieve the current task values, then pass all required fields: task_id, task, owner_id, priority, status, tasklist."
                        }

                    update_data = {
                        "task": task,
                        "owner_id": owner_id,
                        "priority": priority,
                        "status": status,
                        "tasklist": tasklist,
                    }
                    if comments is not None:
                        update_data["comments"] = comments
                    if due_date:
                        update_data["due_date"] = due_date.isoformat()
                    if reminder_options:
                        update_data["reminder_options"] = reminder_options
                    if patient_id:
                        update_data["patient_id"] = patient_id

                    response = strip_empty_values(await client.put(f"/tasks/{task_id}", data=update_data))
                    if (response.get("output_string") or {}).get("message", "").startswith("Success"):
                        response["guidance"] = f"Task {task_id} updated successfully."
                    return response

                case "list":
                    params = {}
                    if view:
                        params["view"] = view
                    if from_date:
                        params["from_date"] = from_date.isoformat()
                    if to_date:
                        params["to_date"] = to_date.isoformat()
                    if page is not None:
                        params["page"] = page
                    if per_page is not None:
                        params["per_page"] = per_page
                    # allow API list filtering (legacy)
                    if status:
                        params["status"] = status
                    if patient_id:
                        params["patient_id"] = patient_id

                    response = await client.get("/tasks", params=params)
                    tasks = response.get("tasks") or []
                    total_count = len(tasks)

                    def _normalize_priority(p: Optional[str]) -> Optional[str]:
                        if p is None:
                            return None
                        s = str(p).strip()
                        if not s:
                            return None
                        s_cf = s.casefold()
                        if s_cf in {"0", "1", "2", "3"}:
                            return s_cf
                        name_map = {
                            "low": "0",
                            "medium": "1",
                            "high": "2",
                            "critical": "3",
                        }
                        return name_map.get(s_cf) or s

                    eff_status_filter = status_filter or status
                    eff_owner_filter = owner_filter or owner_id
                    eff_priority_filter = priority_filter or priority

                    filters: Dict[str, Any] = {}
                    if eff_status_filter:
                        filters["status"] = eff_status_filter
                    if eff_owner_filter:
                        filters["owner_id"] = eff_owner_filter
                    if eff_priority_filter:
                        filters["priority"] = _normalize_priority(eff_priority_filter)

                    filtered = filter_items(tasks, filters=filters or None, limit=limit)
                    response["tasks"] = filtered["items"]
                    response["total_count"] = total_count
                    response["filtered_count"] = filtered["filtered_count"]

                    if response.get("tasks") is not None:
                        response["guidance"] = (
                            f"Found {total_count} tasks; {filtered['filtered_count']} match the provided filters."
                            " Use action='add' to create new tasks, action='update' to modify existing tasks, or action='change_status' to update task status."
                        )
                    return strip_empty_values(response)

                case "change_status":
                    if not task_id or not status:
                        return {"error": "task_id and status are required for change_status"}
                    return strip_empty_values(await client.put(f"/tasks/{task_id}/status", data={"status": status}))
        except Exception as e:
            logger.error(f"Error in manageTasks: {e}")
            return {
                "error": str(e),
                "guidance": f"Task {action} failed. Check your parameters and try again. Use manageTasks(action='list') to verify task IDs."
            }