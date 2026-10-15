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

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

_API_PATH = "/api/ehr/v1"


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

    @property
    def is_user_scoped(self) -> bool:
        return bool(self.access_token or self.refresh_token)

    def client_kwargs(self) -> Dict[str, Any]:
        """Keyword arguments for ``CharmHealthAPIClient``.

        ``accounts_server`` is not a client argument — it only exists to derive
        ``token_url``, which ``resolve_auth`` has already done.
        """
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "base_url": self.base_url,
            "token_url": self.token_url,
            "client_secret": self.client_secret,
        }


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

    access_token = headers.get("x-user-access-token") or _bearer_token(headers)
    refresh_token = headers.get("x-user-refresh-token")
    base_url = headers.get("x-charmhealth-base-url")
    token_url = headers.get("x-charmhealth-token-url")
    client_secret = headers.get("x-charmhealth-client-secret")
    accounts_server = headers.get("x-charmhealth-accounts-server")

    # The mobile flow sends an accounts server rather than a token URL.
    if accounts_server:
        token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"

    if base_url and not base_url.endswith(_API_PATH):
        base_url = base_url.rstrip("/") + _API_PATH

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
