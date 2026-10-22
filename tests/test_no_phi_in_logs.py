"""No patient data or token material reaches the log (CH-1576 / GHSA-vj7g).

The leaks this guards against were never one bug. A response body logged on
every call, token prefixes, a diagnosis tool logging its request and reply,
httpx writing each request URL with its query string, and a failed token
refresh logging the OAuth server's reply. Each was a single line, and the
first ones were removed while the others shipped.

So these tests do not check particular log lines. They run real tools over a
real httpx client, with only the transport underneath replaced, plant marker
values in the arguments and the API's replies, and fail if a marker appears
anywhere in what was logged at INFO or above (the level the stderr handler
in `mcp_server.py` lets through). A new line that leaks fails here whichever
logger wrote it.
"""

from __future__ import annotations

import json
import logging

import httpx
import pytest
from fastmcp.exceptions import ToolError

from api.api_client import CharmHealthAPIClient
from tools import clinical_data, core_tools

PATIENT_NAME = "Zebulon Quixmarker"
DIAGNOSIS_NOTE = "marker-note-7f3a"
SECRET_TOKEN = "marker-token-9c1e"


@pytest.fixture(autouse=True)
def _server_credentials(monkeypatch):
    # Explicit values so nothing from a local .env is used.
    monkeypatch.setenv("CHARMHEALTH_BASE_URL", "https://ehr.example.test/api/ehr/v1")
    monkeypatch.setenv("CHARMHEALTH_TOKEN_URL", "https://accounts.example.test/oauth/v2/token")
    monkeypatch.setenv("CHARMHEALTH_CLIENT_ID", "cid")
    monkeypatch.setenv("CHARMHEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CHARMHEALTH_REFRESH_TOKEN", "server-refresh-token")
    monkeypatch.setenv("CHARMHEALTH_API_KEY", "k")
    CharmHealthAPIClient._shared_token_cache.clear()
    yield
    CharmHealthAPIClient._shared_token_cache.clear()


def _install_transport(monkeypatch, handler):
    """Answer every request in-process. httpx still logs as it would live,
    because its request log line is written above the transport."""

    async def handle(self, request: httpx.Request) -> httpx.Response:
        return handler(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)


def _token_ok(request: httpx.Request) -> httpx.Response | None:
    if request.url.host == "accounts.example.test":
        return httpx.Response(200, json={"access_token": SECRET_TOKEN, "expires_in": 3600})
    return None


def _assert_no_markers(caplog, *markers: str) -> None:
    logged = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.INFO)
    for marker in markers:
        assert marker not in logged, f"{marker!r} reached the log:\n{logged}"


async def test_patient_search_by_name(monkeypatch, caplog):
    first, last = PATIENT_NAME.split()

    def handler(request):
        if (resp := _token_ok(request)) is not None:
            return resp
        return httpx.Response(200, json={"patients": [
            {"patient_id": "1", "first_name": first, "last_name": last, "dob": "1970-01-01"}
        ], "page_context": {}})

    _install_transport(monkeypatch, handler)
    caplog.set_level(logging.INFO)

    await core_tools.findPatients(query=PATIENT_NAME, search_type="name")

    _assert_no_markers(caplog, first, last, SECRET_TOKEN)


async def test_diagnosis_add(monkeypatch, caplog):
    def handler(request):
        if (resp := _token_ok(request)) is not None:
            return resp
        return httpx.Response(200, json={"patient_diagnoses": [
            {"diagnosis_name": "Hypertension", "comments": DIAGNOSIS_NOTE}
        ]})

    _install_transport(monkeypatch, handler)
    caplog.set_level(logging.INFO)

    await clinical_data.managePatientDiagnoses(
        action="add", patient_id="100000000000000001",
        diagnosis_name="Hypertension", diagnosis_code="I10", code_type="ICD10",
        comments=DIAGNOSIS_NOTE,
    )

    _assert_no_markers(caplog, DIAGNOSIS_NOTE, "Hypertension", SECRET_TOKEN)


async def test_ehr_error_reply(monkeypatch, caplog):
    """An error reply can echo the record it rejected. The caller gets that
    text; the log must not."""

    def handler(request):
        if (resp := _token_ok(request)) is not None:
            return resp
        return httpx.Response(400, text=json.dumps({"message": f"Invalid comments: {DIAGNOSIS_NOTE}"}))

    _install_transport(monkeypatch, handler)
    caplog.set_level(logging.INFO)

    with pytest.raises(ToolError) as excinfo:
        await clinical_data.managePatientDiagnoses(
            action="add", patient_id="100000000000000001",
            diagnosis_name="Hypertension", diagnosis_code="I10", code_type="ICD10",
            comments=DIAGNOSIS_NOTE,
        )

    assert DIAGNOSIS_NOTE in str(excinfo.value)
    _assert_no_markers(caplog, DIAGNOSIS_NOTE)


@pytest.mark.parametrize("token_reply", [
    httpx.Response(400, json={"error": "invalid_code", "refresh_token": SECRET_TOKEN}),
    httpx.Response(200, json={"error": "invalid_code", "refresh_token": SECRET_TOKEN}),
], ids=["error-status", "no-access-token"])
async def test_failed_token_refresh(monkeypatch, caplog, token_reply):
    def handler(request):
        if request.url.host == "accounts.example.test":
            return token_reply
        return httpx.Response(200, json={"patients": []})

    _install_transport(monkeypatch, handler)
    caplog.set_level(logging.INFO)

    with pytest.raises(ToolError):
        await core_tools.findPatients(query=PATIENT_NAME, search_type="name")

    _assert_no_markers(caplog, SECRET_TOKEN)
