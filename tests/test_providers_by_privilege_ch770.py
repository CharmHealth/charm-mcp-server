"""Tests for CH-770's role/scope-of-practice signal:
getPracticeInfo(info_type="providers_by_privilege").

Generalizes the existing /members?privilege=sign_encounter filter (used by
the "providers"/"overview" cases) to accept any RBAC privilege token —
cortex's guardrail/gate context checks whether a given member_id appears in
the returned list to answer "may this provider perform this class of
action" (e.g. privilege="add_medications" for prescribing authority).
Fakes CharmHealthAPIClient — same pattern as test_procedure_codes_ch790.py.
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from tools import core_tools


class _FakeAPIClient:
    def __init__(self, get_responses=None):
        self._get = get_responses or {}
        self.get_calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        self.get_calls.append((endpoint, params))
        return self._get[endpoint]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(core_tools, "CharmHealthAPIClient", lambda **kwargs: fake_client)


@pytest.mark.asyncio
async def test_providers_by_privilege_happy_path(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/members": {"members": [
            {"member_id": "m1", "full_name": "Dr. Jane Prescriber"},
        ]},
    })
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="providers_by_privilege", privilege="add_medications")

    assert result["privilege"] == "add_medications"
    assert result["provider_count"] == 1
    assert result["providers"][0]["member_id"] == "m1"
    assert result["providers"][0]["provider_name"] == "Dr. Jane Prescriber"
    assert result["list_truncated"] is False
    # trimmed to identity fields only — no email/phone/address/NPI etc.
    assert set(result["providers"][0].keys()) <= {"member_id", "full_name", "provider_name"}
    endpoint, params = fake.get_calls[0]
    assert endpoint == "/members"
    assert params == {"privilege": "add_medications", "per_page": 100}


@pytest.mark.asyncio
async def test_providers_by_privilege_member_not_in_list_means_unauthorized(monkeypatch) -> None:
    """The consumer-side check is membership in this list, not a boolean
    field — a provider who lacks the privilege simply doesn't appear."""
    fake = _FakeAPIClient(get_responses={
        "/members": {"members": [{"member_id": "m1"}]},
    })
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="providers_by_privilege", privilege="add_medications")

    assert "m2" not in {p["member_id"] for p in result["providers"]}


@pytest.mark.asyncio
async def test_providers_by_privilege_empty_result(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={"/members": {}})
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="providers_by_privilege", privilege="add_medications")

    assert result["provider_count"] == 0
    assert result["providers"] == []


@pytest.mark.asyncio
async def test_providers_by_privilege_missing_privilege_returns_clean_error(monkeypatch) -> None:
    """Matches getPracticeInfo's existing house convention (e.g.
    "template_details" without template_ids): a plain {"error": ...} dict
    returned from the case block, which @with_tool_metrics()'s J13/CH-695
    isError handling then raises as a ToolError at the protocol layer."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await core_tools.getPracticeInfo.fn(info_type="providers_by_privilege")

    assert json.loads(str(exc_info.value))["error"] == "privilege required for providers_by_privilege"
    assert fake.get_calls == []


@pytest.mark.asyncio
async def test_providers_by_privilege_unrecognized_token_returns_clean_error(monkeypatch) -> None:
    """Unconfirmed privilege tokens must be rejected loudly, not silently passed
    through — the backend's behavior for an unrecognized token is undocumented,
    and this list feeds a hard authorization gate downstream."""
    fake = _FakeAPIClient()
    _patch_client(monkeypatch, fake)

    with pytest.raises(ToolError) as exc_info:
        await core_tools.getPracticeInfo.fn(info_type="providers_by_privilege", privilege="some_made_up_privilege")

    assert "Unrecognized privilege token" in json.loads(str(exc_info.value))["error"]
    assert fake.get_calls == []


@pytest.mark.asyncio
async def test_providers_by_privilege_truncated_list_is_flagged(monkeypatch) -> None:
    fake = _FakeAPIClient(get_responses={
        "/members": {
            "members": [{"member_id": "m1", "full_name": "Dr. Jane Prescriber"}],
            "page_context": {"has_more_page": True},
        },
    })
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="providers_by_privilege", privilege="add_medications")

    assert result["list_truncated"] is True
    assert "truncated" in result["guidance"].lower()
