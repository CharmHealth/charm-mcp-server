"""Tests for CharmHealthAPIClient._make_request's 401/refresh handling.

Covers the fix for a real incident (2026-08-13): a single endpoint returning a
401 (confirmed to be a scope gap, not an expired token — same pattern already
documented for /drug/search) was retried up to max_retries (3) times, each
retry forcibly clearing _shared_token_cache — a class-level cache keyed by
client_id+refresh_token and therefore shared by every other in-flight call
using the same credentials. When the underlying refresh_token turned out to
be dead, one of those forced refreshes failed with `access_denied`, and
because _get_auth_headers() was called *outside* _make_request's try block,
that failure propagated as an unhandled exception — bypassing metrics and
surfacing to the caller as a raw, ugly ValueError — while having already
wiped the shared cache that unrelated tools (getPracticeInfo, managePatientLabs)
were successfully reusing, taking them down too.

Two fixes, tested here:
1. A 401 now forces at most one refresh-and-retry per request (an
   `auth_retried` flag), not up to max_retries — a 401 that survives a
   freshly refreshed token is a scope problem a refresh can't fix, so further
   retries only repeat the same failure and the same cache-wipe blast radius.
2. _get_auth_headers() is now called inside the try block, so a failed
   refresh returns a clean {"error": ...} dict instead of an unhandled
   exception.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from api.api_client import CharmHealthAPIClient


def _make_client(**overrides):
    kwargs = dict(
        base_url="https://example.test/api/ehr/v1",
        refresh_token="rt",
        client_id="cid",
        client_secret="secret",
        token_url="https://example.test/oauth/token",
    )
    kwargs.update(overrides)
    return CharmHealthAPIClient(**kwargs)


@pytest.fixture(autouse=True)
def _clear_shared_token_cache():
    # The cache is class-level (shared across instances by design) — reset it
    # around each test so tests don't leak state into each other.
    CharmHealthAPIClient._shared_token_cache.clear()
    yield
    CharmHealthAPIClient._shared_token_cache.clear()


async def test_401_forces_exactly_one_refresh_and_retry_not_max_retries():
    client = _make_client(access_token="initial-token")
    await client.ensure_client()

    unauthorized = httpx.Response(
        401, request=httpx.Request("GET", "https://example.test/x"), text="scope denied"
    )
    client._client.get = AsyncMock(return_value=unauthorized)

    with patch.object(
        client, "_refresh_token", new=AsyncMock(return_value="refreshed-token")
    ) as mock_refresh:
        result = await client.get("/referrals/out")

    # A 401 that persists after a genuine refresh is a scope problem, not an
    # expiry problem — the old code retried this 3 times (max_retries),
    # wiping the shared cache on every attempt. Now it retries once.
    assert result == {"error": "HTTP 401: scope denied"}
    assert mock_refresh.await_count == 1
    assert client._client.get.await_count == 2  # original attempt + the one retry


async def test_401_retry_that_succeeds_returns_the_real_result():
    client = _make_client(access_token="initial-token")
    await client.ensure_client()

    unauthorized = httpx.Response(401, request=httpx.Request("GET", "https://example.test/x"))
    ok = httpx.Response(200, json={"code": "0", "referrals": []}, request=httpx.Request("GET", "https://example.test/x"))
    client._client.get = AsyncMock(side_effect=[unauthorized, ok])

    with patch.object(client, "_refresh_token", new=AsyncMock(return_value="refreshed-token")) as mock_refresh:
        result = await client.get("/referrals/out")

    assert result == {"code": "0", "referrals": []}
    assert mock_refresh.await_count == 1


async def test_failed_refresh_returns_clean_error_not_a_raised_exception():
    client = _make_client()  # no access_token — first call must refresh before it can even try the request
    await client.ensure_client()
    client._client.get = AsyncMock()  # should never be reached

    with patch.object(
        client,
        "_refresh_token",
        new=AsyncMock(
            side_effect=ValueError('Failed to obtain new token with response: {"error":"access_denied"}')
        ),
    ):
        result = await client.get("/patients/123/allergies")

    assert isinstance(result, dict)
    assert "access_denied" in result["error"]
    client._client.get.assert_not_awaited()


async def test_refresh_endpoint_401_is_not_mistaken_for_the_target_apis_401():
    """_refresh_token() posts to the OAuth TOKEN endpoint and calls
    response.raise_for_status() there — if that endpoint itself returns a 401 (e.g. a
    bad/rotated client_secret), it raises httpx.HTTPStatusError same as the target API
    would. Fetching headers must be isolated from the target-request try/except: letting
    this reach that except httpx.HTTPStatusError clause would treat e.response (the OAUTH
    server's response) as if it were the target API's, wrongly firing a second refresh
    (which cannot fix a bad client_secret) and mislabeling the OAuth server's error as the
    target endpoint's."""
    client = _make_client()  # no access_token — must refresh before attempting the request
    await client.ensure_client()
    client._client.get = AsyncMock()  # must never be reached

    oauth_401 = httpx.HTTPStatusError(
        "401 from token endpoint",
        request=httpx.Request("POST", "https://example.test/oauth/token"),
        response=httpx.Response(401, request=httpx.Request("POST", "https://example.test/oauth/token"), text="invalid_client"),
    )
    with patch.object(client, "_refresh_token", new=AsyncMock(side_effect=oauth_401)) as mock_refresh:
        result = await client.get("/referrals/out")

    # Exactly one refresh attempt — not two, which would mean the OAuth 401 got routed
    # through the target-request retry-on-401 logic and triggered a second, pointless one.
    assert mock_refresh.await_count == 1
    client._client.get.assert_not_awaited()
    assert isinstance(result, dict)
    # Labeled as a refresh failure, not mislabeled as "HTTP 401: invalid_client" the way
    # the target API's own 401 handler formats its errors — that format would wrongly
    # imply /referrals/out itself returned this response.
    assert "Token refresh failed" in result["error"]


async def test_401_does_not_clear_shared_cache_entry_belonging_to_a_different_refresh_token():
    other_client = _make_client(refresh_token="someone-elses-refresh-token", access_token="their-token")
    other_key = other_client._token_cache_key()
    CharmHealthAPIClient._shared_token_cache[other_key] = {"token": "their-token", "expires_at": 9_999_999_999}

    client = _make_client(access_token="initial-token")
    await client.ensure_client()
    unauthorized = httpx.Response(401, request=httpx.Request("GET", "https://example.test/x"), text="scope denied")
    client._client.get = AsyncMock(return_value=unauthorized)

    with patch.object(client, "_refresh_token", new=AsyncMock(return_value="refreshed-token")):
        await client.get("/referrals/out")

    # Only this client's own cache key should have been touched by its 401 handling.
    assert other_key in CharmHealthAPIClient._shared_token_cache
