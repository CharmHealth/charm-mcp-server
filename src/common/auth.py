"""Per-request auth resolution — one copy, for every tool.

Callers reach this server three ways, and they do not send the same thing:

- **cortex and the iOS app** forward six headers: ``x-user-access-token``,
  ``x-user-refresh-token``, ``x-charmhealth-base-url``,
  ``x-charmhealth-token-url``, ``x-charmhealth-client-secret``,
  ``x-charmhealth-accounts-server``.
- **A bearer-auth MCP client** sends only ``Authorization: Bearer <token>``,
  from an OAuth flow it runs against Zoho on the user's behalf. It sends none of
  the six, and it never gives us a refresh token — it holds that itself.
- **A local stdio client** (Claude Desktop, Cursor) sends nothing at all and is
  expected to authenticate as the server, from the ``CHARMHEALTH_*`` variables
  in ``.env``.
- **cortex, for a user signed in through CHIS** (CH-1574, the AWS-hosted EHR),
  forwards the user's CHIS session in ``x-chis-acting-session``, the practice's
  app group in ``x-account-id``, and the session cookie's name in
  ``x-chis-session-cookie-name``. The EHR is called with that cookie, so it
  applies the user's own permissions. This is the beta's interim: a session
  lasts 24 hours and can't serve unattended runs, which need a per-user grant
  from CHIS.
- **A CHIS caller** sends ``Authorization: Bearer <token>`` and ``x-account-id``
  (the practice's CHIS AppGroup id). Cortex's background runs send a token CHIS
  minted for the practice's service account. The token goes to the EHR unchanged
  as ``Bearer`` with ``X-ACCOUNT-ID``; the EHR reads what kind of token it is.
  ``x-account-id`` is what tells this caller apart from the bearer-auth Zoho
  client above, and only while that client exists: once the Zoho paths are gone,
  every Bearer is a CHIS token and the header only names the practice.

Only the last case is gated. If a call arrives with no per-user token,
``CharmHealthAPIClient`` would fall back to the server's own credentials and
answer successfully — as whatever practice the server is configured for. On a
local server that is the intended mode. On a hosted server reachable by a
third-party client it is a silent cross-tenant answer, so it requires
``CHARMHEALTH_ALLOW_SERVER_CREDENTIALS=1`` to be set explicitly.

Env fallbacks for base URL, token URL and client secret are deliberately *not*
duplicated here — ``CharmHealthAPIClient.__init__`` already does
``x or os.getenv(...)`` for each, so passing ``None`` gets that behaviour.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

_API_PATH = "/api/ehr/v1"

# A CHIS session id is 256 random bits in hex. Checking the shape keeps a value
# with a ';' or a newline out of the Cookie header we build from it.
_CHIS_SESSION = re.compile(r"[0-9a-f]{64}")
# An RFC 6265 cookie name (an RFC 7230 token).
_COOKIE_NAME = re.compile(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+")
_ACCOUNT_ID = re.compile(r"[0-9]+")


def server_credentials_allowed() -> bool:
    """Whether a call with no per-user token may authenticate as the server."""
    return os.getenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", "0").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class AuthContext:
    """Resolved per-request credentials. Any field may be ``None``, in which
    case ``CharmHealthAPIClient`` falls back to its own env variable."""

    access_token: str | None = None
    refresh_token: str | None = None
    base_url: str | None = None
    token_url: str | None = None
    client_secret: str | None = None
    accounts_server: str | None = None
    # The user's CHIS session. repr=False: it is a live credential.
    chis_session: str | None = field(default=None, repr=False)
    account_id: str | None = None
    session_cookie_name: str | None = None

    @property
    def is_user_scoped(self) -> bool:
        return bool(self.access_token or self.refresh_token or self.chis_session)

    def client_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments for ``CharmHealthAPIClient``.

        ``accounts_server`` is not a client argument — it only exists to derive
        ``token_url``, which ``resolve_auth`` has already done.
        """
        kwargs = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "base_url": self.base_url,
            "token_url": self.token_url,
            "client_secret": self.client_secret,
        }
        if self.chis_session:
            kwargs.update(
                chis_session=self.chis_session,
                account_id=self.account_id,
                session_cookie_name=self.session_cookie_name,
            )
        elif self.account_id:
            # Only a CHIS caller adds it, so every other caller builds exactly the
            # client it built before.
            kwargs["account_id"] = self.account_id
        return kwargs


def token_id(token: str | None) -> str:
    """The token's ``jti`` claim, for log lines, or ``-``.

    Read without verifying the signature: the value only names the token in logs,
    so a run's lines in cortex, here and in CHIS can be matched up. Nothing here
    trusts it; the EHR verifies the token. The token itself is never logged.
    """
    if not token:
        return "-"
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        jti = json.loads(base64.urlsafe_b64decode(payload)).get("jti")
    except Exception:
        return "-"
    return jti if isinstance(jti, str) and jti else "-"


def _api_base_url(base_url: str | None) -> str | None:
    """A caller's EHR base URL, with the API path added when it lacks one."""
    if base_url and not base_url.endswith(_API_PATH):
        return base_url.rstrip("/") + _API_PATH
    return base_url


def _bearer_token(headers: Dict[str, str]) -> str | None:
    """Pull the token out of ``Authorization: Bearer <token>``, if present."""
    raw = headers.get("authorization") or ""
    scheme, _, token = raw.partition(" ")
    if scheme.strip().lower() != "bearer":
        return None
    return token.strip() or None


def resolve_auth(tool_name: str) -> AuthContext:
    """Resolve credentials for the current request.

    Raises ``ToolError`` when no per-user token is present and the server is not
    configured to act as itself.
    """
    headers: Dict[str, str] = {}
    try:
        # `authorization` is on FastMCP's default exclude list, so a bare
        # get_http_headers() silently drops the only credential a bearer-auth client sends
        # and every request falls through to the server's own account. The
        # `include` parameter exists for exactly this case.
        headers = get_http_headers(include={"authorization"}) or {}
    except TypeError:
        # A signature mismatch is a bug here, not a missing request context.
        # Swallowing it costs every caller its credentials silently — which is
        # exactly how the missing `include={"authorization"}` went unnoticed.
        raise
    except Exception as exc:  # no request context — stdio, or a direct call
        logger.debug("No HTTP headers available (likely stdio mode): %s", exc)

    bearer = _bearer_token(headers)
    account_id = (headers.get("x-account-id") or "").strip()
    if bearer and headers.get("x-chis-acting-session"):
        raise ToolError(
            "Send one credential: x-chis-acting-session or an access token, not both."
        )
    if bearer and account_id:
        # A CHIS caller: the token goes to the EHR as it came. None of the Zoho
        # fields apply, so none are read.
        logger.info("%s using a CHIS bearer token jti=%s account=%s",
                    tool_name, token_id(bearer), account_id)
        return AuthContext(
            access_token=bearer,
            base_url=_api_base_url(headers.get("x-charmhealth-base-url")),
            account_id=account_id,
        )

    access_token = headers.get("x-user-access-token") or bearer
    refresh_token = headers.get("x-user-refresh-token")
    base_url = headers.get("x-charmhealth-base-url")
    token_url = headers.get("x-charmhealth-token-url")
    client_secret = headers.get("x-charmhealth-client-secret")
    accounts_server = headers.get("x-charmhealth-accounts-server")

    chis_session = headers.get("x-chis-acting-session")
    if chis_session:
        if access_token or refresh_token:
            raise ToolError(
                "Send one credential: x-chis-acting-session or an access token, not both."
            )
        account_id = headers.get("x-account-id")
        cookie_name = headers.get("x-chis-session-cookie-name")
        # Fail closed on anything malformed. Never echo the session in the error.
        if not _CHIS_SESSION.fullmatch(chis_session):
            raise ToolError("x-chis-acting-session is not a CHIS session id.")
        if not cookie_name or not _COOKIE_NAME.fullmatch(cookie_name):
            raise ToolError("x-chis-session-cookie-name is missing or not a cookie name.")
        if not account_id or not _ACCOUNT_ID.fullmatch(account_id):
            raise ToolError("x-account-id is missing or not an app group id.")
        if base_url and not base_url.endswith(_API_PATH):
            base_url = base_url.rstrip("/") + _API_PATH
        logger.info("%s using the caller's CHIS session", tool_name)
        return AuthContext(
            base_url=base_url,
            chis_session=chis_session,
            account_id=account_id,
            session_cookie_name=cookie_name,
        )

    # The mobile flow sends an accounts server rather than a token URL.
    if accounts_server:
        token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"

    base_url = _api_base_url(base_url)

    context = AuthContext(
        access_token=access_token,
        refresh_token=refresh_token,
        base_url=base_url,
        token_url=token_url,
        client_secret=client_secret,
        accounts_server=accounts_server,
    )

    if context.is_user_scoped:
        # Never log the token or any prefix of it — it is a live credential.
        logger.info("%s using per-user credentials", tool_name)
        return context

    if not server_credentials_allowed():
        raise ToolError(
            "No user credentials were supplied for this request. Send either an "
            "'Authorization: Bearer <token>' header or the 'x-user-access-token' "
            "header. This server is not configured to act on its own credentials "
            "(set CHARMHEALTH_ALLOW_SERVER_CREDENTIALS=1 only on a deployment that "
            "is meant to authenticate as itself, such as a local stdio server)."
        )

    logger.info("%s using server credentials from the environment", tool_name)
    return context
