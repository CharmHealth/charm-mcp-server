"""A CHIS caller: ``Authorization: Bearer`` with ``x-account-id``.

Cortex's background runs send a token CHIS minted for the practice's service
account. It must reach the EHR exactly as it came, as ``Bearer`` with
``X-ACCOUNT-ID`` (the practice's AppGroup id), never rewritten to
``Zoho-oauthtoken`` and never refreshed. Every other caller gets the client it
got before.
"""

from __future__ import annotations

import base64
import json
import logging
from unittest.mock import AsyncMock

import httpx
import pytest

from api.api_client import CharmHealthAPIClient
from common import auth as auth_module
from common.auth import resolve_auth, token_id

JTI = "6d2b1233-955a-4687-85a7-dec4a5dfb150"
ACCOUNT = "900000000002"


def _jwt(claims: dict) -> str:
    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2lnbmF0dXJl"


MINTED = _jwt({"jti": JTI, "sub": "900000000200", "token_use": "client_credentials"})


def _fake_headers(monkeypatch, headers: dict) -> None:
    monkeypatch.setattr(auth_module, "get_http_headers",
                        lambda include_all=False, include=None: headers)


def _response(status: int, **kwargs) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", "https://ehr.test/x"), **kwargs)


# ── resolve_auth ───────────────────────────────────────────────────────


def test_bearer_with_account_id_is_a_chis_caller(monkeypatch) -> None:
    _fake_headers(monkeypatch, {
        "authorization": f"Bearer {MINTED}",
        "x-account-id": ACCOUNT,
        "x-charmhealth-base-url": "https://ehr.test",
    })

    ctx = resolve_auth("findPatients")

    assert ctx.access_token == MINTED
    assert ctx.account_id == ACCOUNT
    assert ctx.base_url == "https://ehr.test/api/ehr/v1"
    assert ctx.client_kwargs()["account_id"] == ACCOUNT


def test_a_chis_caller_reads_none_of_the_zoho_fields(monkeypatch) -> None:
    _fake_headers(monkeypatch, {
        "authorization": f"Bearer {MINTED}",
        "x-account-id": ACCOUNT,
        "x-user-refresh-token": "zoho-refresh",
        "x-charmhealth-client-secret": "zoho-secret",
        "x-charmhealth-token-url": "https://accounts.test/oauth/v2/token",
    })

    ctx = resolve_auth("findPatients")

    assert (ctx.refresh_token, ctx.client_secret, ctx.token_url) == (None, None, None)


@pytest.mark.parametrize("headers", [
    {"authorization": "Bearer zoho-oauth-token"},
    {"x-user-access-token": "zoho-access", "x-account-id": ACCOUNT},
    {"authorization": "Basic dXNlcjpwYXNz", "x-account-id": ACCOUNT},
])
def test_without_a_bearer_and_account_id_the_caller_gets_mains_client(monkeypatch, headers) -> None:
    _fake_headers(monkeypatch, headers)
    monkeypatch.setenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", "1")

    ctx = resolve_auth("findPatients")

    assert ctx.account_id is None
    assert "account_id" not in ctx.client_kwargs()


# ── the client ─────────────────────────────────────────────────────────


def _chis_client(monkeypatch) -> CharmHealthAPIClient:
    # A CHIS deployment has no Zoho settings; the client must not need them.
    for var in ("CHARMHEALTH_CLIENT_ID", "CHARMHEALTH_API_KEY", "CHARMHEALTH_REFRESH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return CharmHealthAPIClient(base_url="https://ehr.test/api/ehr/v1",
                                access_token=MINTED, account_id=ACCOUNT)


async def test_the_token_goes_to_the_ehr_as_bearer_with_x_account_id(monkeypatch) -> None:
    client = _chis_client(monkeypatch)

    headers = await client._get_auth_headers()

    assert headers["Authorization"] == f"Bearer {MINTED}"
    assert headers["X-ACCOUNT-ID"] == ACCOUNT
    assert "api_key" not in headers


async def test_a_chis_client_sends_no_api_key_header(monkeypatch) -> None:
    client = _chis_client(monkeypatch)
    await client.ensure_client()

    assert "api_key" not in client._client.headers
    await client.close()


async def test_a_zoho_client_still_sends_zoho_oauthtoken() -> None:
    client = CharmHealthAPIClient(base_url="https://ehr.test/api/ehr/v1", api_key="k",
                                  access_token="zoho-access", client_id="cid")

    headers = await client._get_auth_headers()

    assert headers["Authorization"] == "Zoho-oauthtoken zoho-access"
    assert "X-ACCOUNT-ID" not in headers


async def test_a_401_is_not_retried_and_names_the_token(monkeypatch, caplog) -> None:
    client = _chis_client(monkeypatch)
    await client.ensure_client()
    client._client.get = AsyncMock(return_value=_response(401, text="expired"))

    with caplog.at_level(logging.ERROR, logger="api.api_client"):
        result = await client.get("/patients")

    assert result == {"error": "HTTP 401: expired"}
    assert client._client.get.await_count == 1
    assert f"jti={JTI}" in caplog.text
    assert f"account={ACCOUNT}" in caplog.text


async def test_a_role_refusal_logs_the_ehrs_error_code(monkeypatch, caplog) -> None:
    client = _chis_client(monkeypatch)
    await client.ensure_client()
    refused = _response(403, json={"code": 1097, "message": "You do not have sufficient privileges"})
    client._client.get = AsyncMock(return_value=refused)

    with caplog.at_level(logging.ERROR, logger="api.api_client"):
        await client.get("/patients/1/allergies")

    assert "HTTP error 403" in caplog.text
    assert "code=1097" in caplog.text
    assert f"jti={JTI}" in caplog.text


async def test_no_log_line_carries_the_token(monkeypatch, caplog) -> None:
    _fake_headers(monkeypatch, {"authorization": f"Bearer {MINTED}", "x-account-id": ACCOUNT})
    client = _chis_client(monkeypatch)
    await client.ensure_client()
    client._client.get = AsyncMock(return_value=_response(403, json={"code": 1097}))

    with caplog.at_level(logging.DEBUG):
        resolve_auth("findPatients")
        await client.get("/patients")

    assert JTI in caplog.text  # the lines were written, and name the token
    for piece in MINTED.split("."):
        assert piece not in caplog.text


# ── token_id ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("token", [None, "", "not-a-jwt", "a.%%%.c", _jwt({"sub": "x"})])
def test_token_id_is_a_dash_when_there_is_no_jti(token) -> None:
    assert token_id(token) == "-"


def test_token_id_reads_the_jti() -> None:
    assert token_id(MINTED) == JTI


@pytest.mark.parametrize("jti", [
    "abc\n2026-11-28 00:00:00 - INFO - forged line",
    "has space",
    "x" * 129,
    "",
])
def test_token_id_refuses_a_jti_that_could_forge_a_log_line(jti) -> None:
    assert token_id(_jwt({"jti": jti})) == "-"


# ── credential_key ─────────────────────────────────────────────────────


def test_one_chis_token_gets_a_separate_cache_key_per_practice(monkeypatch) -> None:
    practice_a = _chis_client(monkeypatch)
    practice_b = CharmHealthAPIClient(base_url="https://ehr.test/api/ehr/v1",
                                      access_token=MINTED, account_id="900000000003")

    assert practice_a.credential_key() != practice_b.credential_key()
    assert practice_a.credential_key() == _chis_client(monkeypatch).credential_key()
