"""CH-1574: cortex forwards a CHIS-signed-in user's session, and the EHR is
called with that cookie.

What a call must carry, from local tests against the AWS-hosted EHR: the
session in the Cookie header, the app group (not the EHR practice id) in
X-ACCOUNT-ID, and no Authorization, since the EHR checks a Bearer first.
"""

from __future__ import annotations

import httpx
import pytest
from fastmcp.exceptions import ToolError

from api import api_client as api_client_module
from api.api_client import CharmHealthAPIClient
from common import auth as auth_module
from common.auth import resolve_auth

SESSION = "ab" * 32
APP_GROUP = "900000000002"


def _fake_headers(monkeypatch, headers: dict) -> None:
    monkeypatch.setattr(auth_module, "get_http_headers",
                        lambda include_all=False, include=None: headers)


def _session_headers(**overrides) -> dict:
    headers = {
        "x-chis-acting-session": SESSION,
        "x-account-id": APP_GROUP,
        "x-chis-session-cookie-name": "CHARM_SID",
        "x-charmhealth-base-url": "https://ehr.test",
    }
    headers.update(overrides)
    return {k: v for k, v in headers.items() if v is not None}


# ── resolve_auth ───────────────────────────────────────────────────────


def test_a_forwarded_session_is_a_user_credential(monkeypatch) -> None:
    monkeypatch.delenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", raising=False)
    _fake_headers(monkeypatch, _session_headers())

    ctx = resolve_auth("findPatients")

    assert ctx.is_user_scoped
    assert ctx.chis_session == SESSION
    assert ctx.account_id == APP_GROUP
    assert ctx.session_cookie_name == "CHARM_SID"
    assert ctx.base_url == "https://ehr.test/api/ehr/v1"
    assert ctx.access_token is None and ctx.refresh_token is None


def test_the_session_never_appears_in_the_contexts_repr(monkeypatch) -> None:
    _fake_headers(monkeypatch, _session_headers())

    assert SESSION not in repr(resolve_auth("findPatients"))


@pytest.mark.parametrize("extra", [
    {"x-user-access-token": "zoho"},
    {"authorization": "Bearer zoho"},
    {"x-user-refresh-token": "rt"},
])
def test_a_session_and_a_token_together_are_refused(monkeypatch, extra) -> None:
    _fake_headers(monkeypatch, _session_headers(**extra))

    with pytest.raises(ToolError, match="one credential"):
        resolve_auth("findPatients")


@pytest.mark.parametrize("override", [
    {"x-chis-acting-session": SESSION + "; other=1"},
    {"x-chis-acting-session": "not-a-session"},
    {"x-chis-session-cookie-name": None},
    {"x-chis-session-cookie-name": "CHARM_SID; x"},
    {"x-account-id": None},
    {"x-account-id": "9000\r\nX-Evil: 1"},
])
def test_a_malformed_session_request_fails_closed(monkeypatch, override) -> None:
    monkeypatch.setenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", "1")
    _fake_headers(monkeypatch, _session_headers(**override))

    with pytest.raises(ToolError) as excinfo:
        resolve_auth("findPatients")
    assert SESSION not in str(excinfo.value)


# ── CharmHealthAPIClient ───────────────────────────────────────────────


@pytest.fixture
def ehr(monkeypatch):
    """Route the client's HTTP through a recorder that answers like the EHR."""
    seen: list[httpx.Request] = []
    status = {"code": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status["code"] != 200:
            return httpx.Response(status["code"], text="<html>error</html>")
        return httpx.Response(200, json={"patients": []})

    real = httpx.AsyncClient

    def with_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(api_client_module.httpx, "AsyncClient", with_transport)
    return seen, status


def _session_client(**overrides) -> CharmHealthAPIClient:
    kwargs = dict(
        base_url="https://ehr.test/api/ehr/v1",
        client_id="cid",
        chis_session=SESSION,
        account_id=APP_GROUP,
        session_cookie_name="CHARM_SID",
    )
    kwargs.update(overrides)
    return CharmHealthAPIClient(**kwargs)


async def test_the_ehr_gets_the_cookie_and_the_app_group_and_no_bearer(ehr, monkeypatch) -> None:
    # The server's own key and refresh token must not ride along.
    monkeypatch.setenv("CHARMHEALTH_API_KEY", "server-key")
    monkeypatch.setenv("CHARMHEALTH_REFRESH_TOKEN", "server-refresh")
    seen, _ = ehr

    async with _session_client() as client:
        result = await client.get("/patients/bulk")

    assert result == {"patients": []}
    (request,) = seen
    assert request.headers["cookie"] == f"CHARM_SID={SESSION}"
    assert request.headers["x-account-id"] == APP_GROUP
    assert "authorization" not in request.headers
    assert "api_key" not in request.headers
    assert client.refresh_token is None


async def test_a_write_carries_the_same_credential(ehr) -> None:
    seen, _ = ehr

    async with _session_client() as client:
        await client.post("/patients/bulk", data=[{"first_name": "A"}])

    assert seen[0].method == "POST"
    assert seen[0].headers["cookie"] == f"CHARM_SID={SESSION}"
    assert "authorization" not in seen[0].headers


async def test_a_rejected_session_is_not_refreshed_or_retried(ehr) -> None:
    seen, status = ehr
    status["code"] = 401

    async with _session_client() as client:
        result = await client.get("/patients/bulk")

    assert len(seen) == 1
    assert "sign in again" in result["error"]
    assert SESSION not in result["error"]


def test_a_session_without_its_app_group_is_refused() -> None:
    with pytest.raises(ValueError):
        _session_client(account_id=None)


def test_two_users_sessions_do_not_share_a_cache_key() -> None:
    a = _session_client()
    b = _session_client(chis_session="cd" * 32)
    other_practice = _session_client(account_id="900000000102")

    assert len({a.credential_key(), b.credential_key(), other_practice.credential_key()}) == 3


async def test_a_session_needs_no_zoho_client_id(ehr, monkeypatch) -> None:
    # A session caller sends no Zoho credential, so a server with no
    # CHARMHEALTH_CLIENT_ID configured (lighthouse) must still call the EHR.
    monkeypatch.delenv("CHARMHEALTH_CLIENT_ID", raising=False)
    seen, _ = ehr

    async with _session_client(client_id=None) as client:
        await client.post("/tasks", data={"task": "A"})

    assert seen[0].headers["cookie"] == f"CHARM_SID={SESSION}"


def test_the_session_reaches_the_client_through_client_kwargs(monkeypatch) -> None:
    monkeypatch.setenv("CHARMHEALTH_CLIENT_ID", "cid")
    _fake_headers(monkeypatch, _session_headers())

    client = CharmHealthAPIClient(**resolve_auth("findPatients").client_kwargs())

    assert client._chis_session == SESSION
    assert client._account_id == APP_GROUP
    assert client.refresh_token is None
