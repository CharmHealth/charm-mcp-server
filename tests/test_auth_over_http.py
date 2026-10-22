"""Auth against the real header pipeline, not a stand-in.

`tests/test_auth_resolution.py` fakes `get_http_headers`, which is fast and
covers the resolution rules — but it cannot catch what the real function *does*
to the headers on the way through. FastMCP excludes `authorization` from
`get_http_headers()` by default, so a bare call silently drops the only
credential a bearer-auth client sends and every request falls back to the server's own
account. Ten commits and 261 mocked tests did not notice; running the server
over HTTP and watching the log line did.

These tests drive `resolve_auth` through FastMCP's actual request context.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from common.auth import resolve_auth
from fastmcp.server.dependencies import _current_http_request


def _request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


@pytest.fixture
def http_request():
    """Install a real Starlette request the way the HTTP transport does."""
    tokens = []

    def _install(headers: dict[str, str]) -> None:
        tokens.append(_current_http_request.set(_request(headers)))

    yield _install
    for token in reversed(tokens):
        _current_http_request.reset(token)


def test_bearer_token_survives_fastmcps_header_filtering(http_request) -> None:
    """The regression: `authorization` is on FastMCP's default exclude list."""
    http_request({"authorization": "Bearer bearer-oauth-token",
                  "content-type": "application/json"})

    ctx = resolve_auth("findPatients")

    assert ctx.access_token == "bearer-oauth-token"
    assert ctx.is_user_scoped


def test_x_headers_survive_the_same_path(http_request) -> None:
    http_request({"x-user-access-token": "cortex-token",
                  "x-user-refresh-token": "cortex-refresh",
                  "x-charmhealth-base-url": "https://ehr.example.com"})

    ctx = resolve_auth("findPatients")

    assert ctx.access_token == "cortex-token"
    assert ctx.refresh_token == "cortex-refresh"
    assert ctx.base_url == "https://ehr.example.com/api/ehr/v1"


def test_a_signature_mismatch_is_not_swallowed(monkeypatch) -> None:
    """resolve_auth catches "no request context" broadly. A TypeError is a bug,
    not a missing context, and swallowing it costs every caller its credentials
    silently — which is how the missing `include` went unnoticed."""
    from common import auth as auth_module

    monkeypatch.setattr(auth_module, "get_http_headers", lambda: {})  # wrong signature

    with pytest.raises(TypeError):
        resolve_auth("findPatients")


# ── Per-user sessions must not inherit or share server credentials ────


def test_bearer_only_client_does_not_inherit_the_server_refresh_token(monkeypatch) -> None:
    """A bearer-auth client sends an access token and no refresh token — it keeps that and
    re-mints. Inheriting CHARMHEALTH_REFRESH_TOKEN would pair one user's access
    token with the server's refresh token, and the session becomes the server's
    account on the first refresh."""
    from api import CharmHealthAPIClient

    monkeypatch.setenv("CHARMHEALTH_REFRESH_TOKEN", "SERVER-REFRESH-TOKEN")
    monkeypatch.setenv("CHARMHEALTH_CLIENT_ID", "cid")

    client = CharmHealthAPIClient(access_token="bearer-user-token")

    assert client.user_scoped
    assert client.refresh_token is None


@pytest.mark.asyncio
async def test_expired_bearer_session_fails_instead_of_escalating(monkeypatch) -> None:
    import time

    from api import CharmHealthAPIClient

    monkeypatch.setenv("CHARMHEALTH_REFRESH_TOKEN", "SERVER-REFRESH-TOKEN")
    monkeypatch.setenv("CHARMHEALTH_CLIENT_ID", "cid")

    client = CharmHealthAPIClient(access_token="bearer-user-token")
    client._token_expires_at = time.time() - 1

    with pytest.raises(ValueError, match="no per-user refresh token"):
        await client._get_valid_token()


def test_clients_with_their_own_refresh_token_are_unchanged(monkeypatch) -> None:
    """cortex and iOS send both tokens; the shared cache keys on the refresh
    token so their sessions stay separate."""
    from api import CharmHealthAPIClient

    monkeypatch.setenv("CHARMHEALTH_CLIENT_ID", "cid")

    a = CharmHealthAPIClient(access_token="a", refresh_token="refresh-a")
    b = CharmHealthAPIClient(access_token="b", refresh_token="refresh-b")

    assert a.refresh_token == "refresh-a"
    assert a._token_cache_key() != b._token_cache_key()


def test_server_scoped_client_still_uses_the_environment(monkeypatch) -> None:
    """Local stdio has no tokens at all and is expected to act as the server."""
    from api import CharmHealthAPIClient

    monkeypatch.setenv("CHARMHEALTH_REFRESH_TOKEN", "SERVER-REFRESH-TOKEN")
    monkeypatch.setenv("CHARMHEALTH_CLIENT_ID", "cid")

    client = CharmHealthAPIClient()

    assert not client.user_scoped
    assert client.refresh_token == "SERVER-REFRESH-TOKEN"
