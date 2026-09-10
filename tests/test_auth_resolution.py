"""Tests for common/auth.resolve_auth — the single credential resolver.

Three callers, three shapes: cortex and iOS send six `x-*` headers, a
bearer-auth client sends only `Authorization: Bearer`, and a local stdio client
sends nothing and is expected to authenticate as the server.
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from common import auth as auth_module
from common.auth import resolve_auth
from tools import billing


def _fake_headers(monkeypatch, headers: dict) -> None:
    # Accept the kwargs the real function takes. `authorization` is on FastMCP's
    # default exclude list, so resolve_auth must ask for it explicitly — a double
    # that ignored the signature would keep passing while the real path returned
    # no token at all.
    monkeypatch.setattr(auth_module, "get_http_headers",
                        lambda include_all=False, include=None: headers)


# ── Bearer token only ──────────────────────────────────────────────────


def test_bearer_token_is_used_as_the_access_token(monkeypatch) -> None:
    _fake_headers(monkeypatch, {"authorization": "Bearer bearer-oauth-token"})

    ctx = resolve_auth("findPatients")

    assert ctx.access_token == "bearer-oauth-token"
    assert ctx.is_user_scoped
    # Such a client holds the refresh token itself; we never receive one.
    assert ctx.refresh_token is None
    # Base URL and client secret fall through to the client's env fallback.
    assert ctx.base_url is None
    assert ctx.client_secret is None


@pytest.mark.parametrize(
    "value",
    ["Token abc", "bearer", "Bearer ", "", "Basic dXNlcjpwYXNz"],
)
def test_non_bearer_authorization_yields_no_token(monkeypatch, value: str) -> None:
    _fake_headers(monkeypatch, {"authorization": value})
    monkeypatch.setenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", "1")

    assert resolve_auth("findPatients").access_token is None


def test_bearer_scheme_is_case_insensitive(monkeypatch) -> None:
    _fake_headers(monkeypatch, {"authorization": "bearer lower-case-scheme"})

    assert resolve_auth("findPatients").access_token == "lower-case-scheme"


# ── cortex / iOS: the six headers, unchanged from before ──────────────


def test_x_headers_take_precedence_and_are_normalized(monkeypatch) -> None:
    _fake_headers(monkeypatch, {
        "x-user-access-token": "cortex-token",
        "x-user-refresh-token": "cortex-refresh",
        "x-charmhealth-base-url": "https://ehr.example.com/",
        "x-charmhealth-client-secret": "secret",
        "x-charmhealth-accounts-server": "https://accounts.example.com/",
        "authorization": "Bearer should-be-ignored",
    })

    ctx = resolve_auth("findPatients")

    assert ctx.access_token == "cortex-token"
    assert ctx.refresh_token == "cortex-refresh"
    # The API path is appended once, and only when missing.
    assert ctx.base_url == "https://ehr.example.com/api/ehr/v1"
    # The mobile flow sends an accounts server rather than a token URL.
    assert ctx.token_url == "https://accounts.example.com/oauth/v2/token"


def test_base_url_already_carrying_api_path_is_left_alone(monkeypatch) -> None:
    _fake_headers(monkeypatch, {
        "x-user-access-token": "t",
        "x-charmhealth-base-url": "https://ehr.example.com/api/ehr/v1",
    })

    assert resolve_auth("findPatients").base_url == "https://ehr.example.com/api/ehr/v1"


# ── no credentials: gated by the flag ─────────────────────────────────


def test_no_credentials_is_refused_by_default(monkeypatch) -> None:
    _fake_headers(monkeypatch, {})
    monkeypatch.delenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", raising=False)

    with pytest.raises(ToolError) as excinfo:
        resolve_auth("findPatients")

    # The message has to name the flag, or the local setup is unfixable.
    assert "CHARMHEALTH_ALLOW_SERVER_CREDENTIALS" in str(excinfo.value)


def test_no_credentials_is_allowed_when_the_flag_is_set(monkeypatch) -> None:
    _fake_headers(monkeypatch, {})
    monkeypatch.setenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", "1")

    ctx = resolve_auth("findPatients")

    assert not ctx.is_user_scoped
    # All None, so CharmHealthAPIClient falls back to its own env variables.
    assert ctx.client_kwargs() == {
        "access_token": None,
        "refresh_token": None,
        "base_url": None,
        "token_url": None,
        "client_secret": None,
    }


def test_missing_request_context_does_not_crash(monkeypatch) -> None:
    """Pure stdio: get_http_headers() raises rather than returning {}."""
    def _raise(include_all=False, include=None):
        raise RuntimeError("no active request")

    monkeypatch.setattr(auth_module, "get_http_headers", _raise)
    monkeypatch.setenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", "1")

    assert resolve_auth("findPatients").client_kwargs()["access_token"] is None


# ── end to end: the token actually reaches the API client ─────────────


async def test_resolved_token_reaches_the_api_client(monkeypatch) -> None:
    """Guards the wiring, not just the resolver: a bearer token must arrive as
    the client's access_token, or every bearer-auth call would silently run on the
    server's own credentials."""
    captured: dict = {}

    class _RecordingClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, endpoint, params=None):
            return {"total_balance_due": 0.0}

    _fake_headers(monkeypatch, {"authorization": "Bearer end-to-end-token"})
    monkeypatch.setattr(billing, "CharmHealthAPIClient", _RecordingClient)

    await billing.managePatientBilling(action="get_balance", patient_id="p1")

    assert captured["access_token"] == "end-to-end-token"
