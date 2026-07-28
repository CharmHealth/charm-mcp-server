"""Tests for the response_format param on detail-view tools (J13 / CH-695, task 3).

Additive only: the param must be accepted (and validated) without changing
any tool's behavior. These tests check the generated JSON schema and the
same jsonschema validation the MCP SDK runs before a tool ever executes —
no network calls, so no need to mock CharmHealthAPIClient.
"""

from __future__ import annotations

import asyncio

import jsonschema
import pytest

import mcp_server

DETAIL_VIEW_TOOLS_WITH_MIN_ARGS = {
    "manageEncounter": {"patient_id": "p1"},
    "managePatientLabs": {"action": "list"},
    "findPatients": {},
    "manageAppointments": {"action": "list"},
    "managePatient": {"action": "create"},
    "reviewPatientHistory": {"patient_id": "p1"},
}


@pytest.fixture(scope="module")
def tools() -> dict:
    return asyncio.run(mcp_server.mcp_composite_server.get_tools())


@pytest.mark.parametrize("tool_name", DETAIL_VIEW_TOOLS_WITH_MIN_ARGS)
def test_tool_advertises_response_format(tool_name: str, tools: dict) -> None:
    tool = tools[tool_name]
    schema = tool.parameters["properties"]["response_format"]
    allowed = {"concise", "detailed", None}

    enum_values = set()
    for option in schema["anyOf"]:
        if "enum" in option:
            enum_values.update(option["enum"])
        elif option.get("type") == "null":
            enum_values.add(None)

    assert enum_values == allowed
    assert schema["default"] is None


@pytest.mark.parametrize("tool_name,min_args", DETAIL_VIEW_TOOLS_WITH_MIN_ARGS.items())
def test_response_format_detailed_passes_schema_validation(
    tool_name: str, min_args: dict, tools: dict,
) -> None:
    tool = tools[tool_name]
    arguments = {**min_args, "response_format": "detailed"}

    # Same validation the MCP SDK runs before invoking the tool function
    # (mcp/server/lowlevel/server.py: jsonschema.validate(instance=arguments,
    # schema=tool.inputSchema)) — proves cortex's injected argument is
    # accepted, without needing to hit the real CharmHealth API.
    jsonschema.validate(instance=arguments, schema=tool.parameters)


@pytest.mark.parametrize("tool_name,min_args", DETAIL_VIEW_TOOLS_WITH_MIN_ARGS.items())
def test_response_format_omitted_still_passes_schema_validation(
    tool_name: str, min_args: dict, tools: dict,
) -> None:
    # No behavior/validation change for callers who don't pass it at all —
    # this is what every caller does today.
    tool = tools[tool_name]
    jsonschema.validate(instance=min_args, schema=tool.parameters)


@pytest.mark.parametrize("tool_name,min_args", DETAIL_VIEW_TOOLS_WITH_MIN_ARGS.items())
def test_invalid_response_format_value_fails_schema_validation(
    tool_name: str, min_args: dict, tools: dict,
) -> None:
    tool = tools[tool_name]
    arguments = {**min_args, "response_format": "loud"}

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=arguments, schema=tool.parameters)
