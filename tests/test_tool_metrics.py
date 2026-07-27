"""Tests for with_tool_metrics — isError signaling (J13 / CH-695).

A tool's own return dict (error/guidance keys) must stay byte-identical;
the only new behavior is raising ToolError so FastMCP flags isError=True.
"""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError

from telemetry.tool_metrics import with_tool_metrics


@pytest.mark.asyncio
async def test_success_dict_is_returned_unchanged() -> None:
    @with_tool_metrics()
    async def fake_tool() -> dict:
        return {"status": "ok", "guidance": "next call the thing"}

    result = await fake_tool()

    assert result == {"status": "ok", "guidance": "next call the thing"}


@pytest.mark.asyncio
async def test_error_dict_raises_tool_error_with_identical_json() -> None:
    error_payload = {"error": "Patient not found", "guidance": "Verify the patient_id"}

    @with_tool_metrics()
    async def fake_tool() -> dict:
        return error_payload

    with pytest.raises(ToolError) as exc_info:
        await fake_tool()

    # Message must be the exact same JSON the caller would have seen as
    # plain content before this change — same keys, same formatting.
    assert str(exc_info.value) == json.dumps(error_payload, indent=2)
    assert json.loads(str(exc_info.value)) == error_payload


@pytest.mark.asyncio
async def test_error_dict_still_contains_error_and_guidance_keys() -> None:
    # Guards against ever stripping these keys — the iOS app in prod
    # detects failures by sniffing the "error" key in the response text.
    error_payload = {"error": "Appointment slot unavailable", "guidance": "Pick another time"}

    @with_tool_metrics()
    async def fake_tool() -> dict:
        return error_payload

    with pytest.raises(ToolError) as exc_info:
        await fake_tool()

    parsed = json.loads(str(exc_info.value))
    assert "error" in parsed
    assert "guidance" in parsed


@pytest.mark.asyncio
async def test_real_exception_still_propagates_unmodified() -> None:
    @with_tool_metrics()
    async def fake_tool() -> dict:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await fake_tool()


@pytest.mark.asyncio
async def test_non_dict_result_passes_through_without_raising() -> None:
    # Defensive: a tool that (atypically) returns a non-dict must not be
    # mistaken for an error payload just because "error" can't be a key of it.
    @with_tool_metrics()
    async def fake_tool() -> list:
        return [1, 2, 3]

    result = await fake_tool()

    assert result == [1, 2, 3]
