"""Missing HTTP credential fields stay request-scoped; stdio keeps env defaults."""

from unittest.mock import patch

import pytest

from api.api_client import CharmHealthAPIClient

FIELDS = ("api_key", "client_id", "redirect_uri")


@pytest.mark.parametrize("field", FIELDS)
def test_request_header_overrides_environment(field, monkeypatch):
    monkeypatch.setenv("CHARMHEALTH_" + field.upper(), "environment-value")
    headers = {"x-charmhealth-" + name.replace("_", "-"): "request-" + name for name in FIELDS}
    with patch("api.api_client.get_http_headers", return_value=headers):
        client = CharmHealthAPIClient(refresh_token="test-refresh")
    assert getattr(client, field) == "request-" + field


@pytest.mark.parametrize("field", FIELDS)
def test_explicit_constructor_argument_wins(field):
    headers = {"x-charmhealth-" + name.replace("_", "-"): "request-" + name for name in FIELDS}
    with patch("api.api_client.get_http_headers", return_value=headers):
        client = CharmHealthAPIClient(refresh_token="test-refresh", **{field: "explicit-value"})
    assert getattr(client, field) == "explicit-value"


def test_stdio_without_headers_preserves_environment(monkeypatch):
    for field in FIELDS:
        monkeypatch.setenv("CHARMHEALTH_" + field.upper(), "environment-" + field)
    with patch("api.api_client.get_http_headers", return_value={}):
        client = CharmHealthAPIClient(refresh_token="test-refresh")
    assert all(getattr(client, field) == "environment-" + field for field in FIELDS)


def test_next_request_uses_its_own_headers():
    with patch("api.api_client.get_http_headers", side_effect=[
        {"x-charmhealth-" + name.replace("_", "-"): practice + name for name in FIELDS}
        for practice in ("first-", "second-")
    ]):
        first = CharmHealthAPIClient(refresh_token="first-refresh")
        second = CharmHealthAPIClient(refresh_token="second-refresh")
    for field in FIELDS:
        assert getattr(first, field) == "first-" + field
        assert getattr(second, field) == "second-" + field
