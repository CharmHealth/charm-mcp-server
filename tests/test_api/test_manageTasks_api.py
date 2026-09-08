"""Live-server API probe for manageTasks (src/tools/task_management.py).

Run against the already-running MCP server (see tests/test_api/conftest.py). Each test
is the pytest form of a command run manually via scripts/mcp_test_client.py,
and is self-contained (creates its own fresh task) so it can be run alone via
your IDE's per-test run button.

Test data: Peter Parker — owner_id 100010000000000117; tasklist "Patient Care"
(pre-existing in this sandbox, confirmed via list).
"""
import pytest
from conftest import call_tool, TEST_DATA

OWNER_ID = TEST_DATA["provider_id"]
TASKLIST = "Patient Care"


async def _add_task() -> str:
    resp = await call_tool(
        "manageTasks",
        {
            "action": "add",
            "task": "MCP API probe test task",
            "owner_id": OWNER_ID,
            "priority": "1",
            "status": "Pending",
            "tasklist": TASKLIST,
        },
    )
    assert "error" not in resp, f"could not add a test task: {resp}"
    return resp["data"]["task_id"]


async def test_manageTasks_list():
    # $ ... manageTasks '{"action": "list", "view": "All"}'
    resp = await call_tool("manageTasks", {"action": "list", "view": "All"})
    assert "error" not in resp


@pytest.mark.no_delete_available
async def test_manageTasks_add():
    # $ ... manageTasks '{"action": "add", "task": "MCP API probe test task", "owner_id": "100010000000000117", \
    #       "priority": "1", "status": "Pending", "tasklist": "Patient Care"}'
    resp = await call_tool(
        "manageTasks",
        {
            "action": "add",
            "task": "MCP API probe test task",
            "owner_id": OWNER_ID,
            "priority": "1",
            "status": "Pending",
            "tasklist": TASKLIST,
        },
    )
    assert "error" not in resp
    assert resp.get("data", {}).get("task_id")


@pytest.mark.no_delete_available
async def test_manageTasks_update():
    # $ ... manageTasks '{"action": "update", "task_id": "<fresh task_id>", \
    #       "task": "MCP API probe test task - updated", "owner_id": "100010000000000117", \
    #       "priority": "2", "status": "Completed", "tasklist": "Patient Care"}'
    #
    # Originally written with status="In-progress" (matching the docstring) and
    # failed reproducibly with an empty "HTTP 400: ". Root-caused via direct
    # CharmHealthAPIClient calls (bypassing the MCP layer): it's specifically the
    # value "In-progress" (in any spelling/casing tried) that both this endpoint
    # AND change_status's separate endpoint reject -- not a payload-shape bug.
    # This sandbox's real task data has only ever contained "Pending"/"Completed"
    # statuses (confirmed via a full list scan) -- "In-progress" may simply not
    # be a real status value here at all. Not fixable from this side without
    # CharmHealth's actual API docs (the empty 400 body gives no diagnostic
    # detail), so left undiagnosed rather than guess-patched. Using "Completed"
    # here instead, which is confirmed to work, so this test reflects real
    # working behavior. See test_manageTasks_update_in_progress_status_rejected
    # below for the documented "In-progress" finding.
    task_id = await _add_task()
    resp = await call_tool(
        "manageTasks",
        {
            "action": "update",
            "task_id": task_id,
            "task": "MCP API probe test task - updated",
            "owner_id": OWNER_ID,
            "priority": "2",
            "status": "Completed",
            "tasklist": TASKLIST,
        },
    )
    assert "error" not in resp


@pytest.mark.no_delete_available
async def test_manageTasks_update_in_progress_status_rejected():
    # $ ... manageTasks '{"action": "update", "task_id": "<fresh task_id>", \
    #       "task": "...", "owner_id": "100010000000000117", "priority": "1", \
    #       "status": "In-progress", "tasklist": "Patient Care"}'
    #
    # Documents the finding above: "In-progress" is rejected with an empty
    # HTTP 400 on both update and change_status, despite the docstring listing
    # it as a valid status. Not asserted as a bug to fix -- documented as a
    # real, unexplained backend restriction pending CharmHealth's actual docs.
    task_id = await _add_task()
    resp = await call_tool(
        "manageTasks",
        {
            "action": "update",
            "task_id": task_id,
            "task": "MCP API probe test task",
            "owner_id": OWNER_ID,
            "priority": "1",
            "status": "In-progress",
            "tasklist": TASKLIST,
        },
    )
    assert "error" in resp
    assert resp["error"] == "HTTP 400: "


@pytest.mark.no_delete_available
async def test_manageTasks_change_status():
    # $ ... manageTasks '{"action": "change_status", "task_id": "<fresh task_id>", "status": "Completed"}'
    task_id = await _add_task()
    resp = await call_tool(
        "manageTasks",
        {"action": "change_status", "task_id": task_id, "status": "Completed"},
    )
    assert "error" not in resp


@pytest.mark.no_delete_available
async def test_manageTasks_change_status_new_status_param_does_not_exist():
    # $ ... manageTasks '{"action": "change_status", "task_id": "<fresh task_id>", "new_status": "Pending"}'
    #
    # CONFIRMED DOC/CODE MISMATCH: the docstring says change_status "requires
    # task_id + new_status", but there is no `new_status` parameter in the
    # function signature at all -- only `status`. FastMCP's schema rejects it
    # outright before the tool body ever runs: "Unexpected keyword argument".
    # Following the docstring literally fails 100% of the time.
    task_id = await _add_task()
    resp = await call_tool(
        "manageTasks",
        {"action": "change_status", "task_id": task_id, "new_status": "Pending"},
    )
    assert "error" in resp
    assert "Unexpected keyword argument" in resp["error"]
