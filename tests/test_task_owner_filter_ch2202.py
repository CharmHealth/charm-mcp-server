"""Tests for CH-2202: "what are my tasks" was returning empty.

manageTasks(action="list")'s owner_filter/owner_id is matched client-side
against each task's own flattened owner_id (== member_id) after fetching —
never sent to GET /tasks. A value that doesn't exactly match a task's
owner_id silently returns zero results rather than an error, which is what
made the physician-assistant agent report "no tasks assigned" to a provider
who genuinely had some: it filtered by an owner_filter that did not match
the practice's own owner_id values.

view="MyTasks"/"AssignedToMe", by contrast, is forwarded straight to
GET /tasks and relies on CharmHealth's own per-user OAuth token to scope the
result — no ID to get right at all. These tests pin:
  1. view is forwarded to the API and never triggers client-side owner
     filtering.
  2. owner_filter still works correctly when the ID actually matches
     (documents the legitimate "someone else's tasks" path).
  3. a mismatched owner_filter against a non-empty task list surfaces the
     new guidance pointing the caller at view instead of failing silently.
  4. a bare list call with no filters returns everything, unfiltered — no
     implicit default owner scoping is ever reintroduced.

Driven through the real server with fastmcp.Client, same pattern as
test_encounter_list_without_patient.py, since action="list" returns an
app_result()-wrapped ToolResult rather than a plain dict.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

import mcp_server
from tools import task_management


class _FakeAPIClient:
    def __init__(self, get_responses=None):
        self._get = get_responses or {}
        self.get_calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        self.get_calls.append((endpoint, params or {}))
        return self._get[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(task_management, "CharmHealthAPIClient", lambda **kwargs: fake_client)


def _content_text(result) -> str:
    return "\n".join(b.text for b in result.content if hasattr(b, "text"))


def _two_tasks() -> dict:
    # A fresh dict per call — manageTasks mutates the response dict it's
    # handed in place (response["tasks"] = ..., etc.), so a module-level
    # constant reused by reference across tests would leak state between them.
    return {
        "/tasks": {
            "tasks": [
                {"task_id": "t1", "task": "Call patient", "owner": {"member_id": 555, "full_name": "Dr. Smith"}},
                {"task_id": "t2", "task": "Review labs", "owner": {"member_id": 555, "full_name": "Dr. Smith"}},
            ]
        }
    }


@pytest.mark.asyncio
async def test_view_my_tasks_is_forwarded_and_not_owner_filtered(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_two_tasks())
    _patch_client(monkeypatch, fake)

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("manageTasks", {"action": "list", "view": "MyTasks"})

    endpoint, params = fake.get_calls[0]
    assert endpoint == "/tasks"
    assert params == {"view": "MyTasks"}

    payload = json.loads(_content_text(result))
    assert payload["total_count"] == 2
    assert payload["filtered_count"] == 2
    assert [t["task_id"] for t in payload["tasks"]] == ["t1", "t2"]


@pytest.mark.asyncio
async def test_owner_filter_matching_member_id_returns_that_owners_tasks(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/tasks": {
            "tasks": [
                {"task_id": "t1", "owner": {"member_id": 555, "full_name": "Dr. Smith"}},
                {"task_id": "t2", "owner": {"member_id": 999, "full_name": "Dr. Jones"}},
            ]
        }
    })
    _patch_client(monkeypatch, fake)

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("manageTasks", {"action": "list", "owner_filter": "555"})

    payload = json.loads(_content_text(result))
    assert payload["total_count"] == 2
    assert payload["filtered_count"] == 1
    assert [t["task_id"] for t in payload["tasks"]] == ["t1"]


@pytest.mark.asyncio
async def test_mismatched_owner_filter_against_nonempty_tasks_points_at_view(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_two_tasks())
    _patch_client(monkeypatch, fake)

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("manageTasks", {"action": "list", "owner_filter": "not-a-real-id"})

    payload = json.loads(_content_text(result))
    assert payload["total_count"] == 2
    assert payload["filtered_count"] == 0
    assert payload["tasks"] == []
    assert "view='MyTasks'" in payload["guidance"]
    assert "AssignedToMe" in payload["guidance"]


@pytest.mark.asyncio
async def test_bare_list_call_applies_no_implicit_owner_filter(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses=_two_tasks())
    _patch_client(monkeypatch, fake)

    async with Client(mcp_server.mcp_composite_server) as client:
        result = await client.call_tool("manageTasks", {"action": "list"})

    endpoint, params = fake.get_calls[0]
    assert endpoint == "/tasks"
    assert params == {}

    payload = json.loads(_content_text(result))
    assert payload["total_count"] == 2
    assert payload["filtered_count"] == 2
