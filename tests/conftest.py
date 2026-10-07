"""Shared test setup.

Every test in this suite fakes `CharmHealthAPIClient`, so no credential ever
leaves the process and no request is made. But the tools now refuse to run
without a per-user token unless the server is explicitly configured to act on
its own credentials (see `common/auth.resolve_auth`), and calling a tool
function directly — or through an in-memory client — supplies no headers at all.

So the suite opts into the server-credentials path, which is the same posture a
local stdio server runs in. Tests that exercise the flag itself override it with
`monkeypatch`.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _allow_server_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARMHEALTH_ALLOW_SERVER_CREDENTIALS", "1")
