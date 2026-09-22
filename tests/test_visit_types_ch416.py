"""Tests for getPracticeInfo(info_type="visit_types") — the visit-type ->
chart_templates mapping CH-416 needs.

The API side shipped as CH-419 (Vir Jhangiani, "Visittypes API: include
attached chart templates per visit type"); this is the client of it.

The practice links SOAP templates to a visit type in settings; the
visit-types endpoint returns those under "chart_templates" per visit type.
Surfacing them lets a caller attach the configured template with
manageEncounter(action="update", template_ids=...) instead of guessing from
the practice-wide list. Fakes CharmHealthAPIClient — same pattern as
test_procedure_codes_ch790.py.
"""

from __future__ import annotations

import pytest

from tools import core_tools


class _FakeAPIClient:
    def __init__(self, pages=None):
        self._pages = pages or []
        self.get_calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        self.get_calls.append((endpoint, params))
        return self._pages[len(self.get_calls) - 1]


def _patch_client(monkeypatch, fake_client) -> None:
    monkeypatch.setattr(core_tools, "CharmHealthAPIClient", lambda **kwargs: fake_client)


def _page(visittypes, has_more=False):
    return {
        "code": "0",
        "visittypes": visittypes,
        "page_context": {"has_more_page": "true" if has_more else "false"},
    }


# Field names confirmed live against ehr2.charmtracker.com, 2026-09-21.
_LINKED = {
    "visit_type_id": "1995529000000017001",
    "visit_type": "New Patient Visit",
    "duration": "60",
    "appointment_mode": "In Person",
    "chart_templates": [
        {"template_id": "t1", "template_name": "New Patient SOAP", "template_type": "SOAP"},
    ],
}
_UNLINKED = {
    "visit_type_id": "1995529000000017002",
    "visit_type": "Follow Up",
    "duration": "30",
    "appointment_mode": "In Person",
    "chart_templates": [],
}


@pytest.mark.asyncio
async def test_visit_types_passes_chart_templates_through_untouched(monkeypatch) -> None:
    fake = _FakeAPIClient(pages=[_page([_LINKED, _UNLINKED])])
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="visit_types")

    assert result["visit_type_count"] == 2
    linked = result["visit_types"][0]
    assert linked["visit_type_id"] == "1995529000000017001"
    assert linked["chart_templates"] == [
        {"template_id": "t1", "template_name": "New Patient SOAP", "template_type": "SOAP"},
    ]
    endpoint, params = fake.get_calls[0]
    assert endpoint == "/settings/visittypes"
    assert params == {"page": 1, "per_page": 200}


@pytest.mark.asyncio
async def test_visit_type_with_no_linked_template_keeps_an_empty_list(monkeypatch) -> None:
    """Empty is a real answer ("practice linked nothing here"), distinct from
    a build that doesn't return the key at all — strip_empty_values preserves
    empty lists for exactly this reason."""
    fake = _FakeAPIClient(pages=[_page([_UNLINKED])])
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="visit_types")

    assert result["visit_types"][0]["chart_templates"] == []
    assert "0 of 1 visit type(s) have chart_templates configured" in result["guidance"]


@pytest.mark.asyncio
async def test_visit_types_follows_has_more_page(monkeypatch) -> None:
    """per_page isn't honoured on every build (asked 200, got 50 live), so
    pagination has to follow the flag rather than trust one big page."""
    fake = _FakeAPIClient(pages=[
        _page([_LINKED], has_more=True),
        _page([_UNLINKED], has_more=False),
    ])
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="visit_types")

    assert result["visit_type_count"] == 2
    assert [p[1]["page"] for p in fake.get_calls] == [1, 2]


@pytest.mark.asyncio
async def test_visit_types_empty_practice(monkeypatch) -> None:
    fake = _FakeAPIClient(pages=[_page([])])
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="visit_types")

    assert result["visit_type_count"] == 0
    assert result["visit_types"] == []


@pytest.mark.asyncio
async def test_visit_types_tolerates_a_build_without_chart_templates(monkeypatch) -> None:
    """sandbox3 returns visit types with no chart_templates key at all. The
    tool must still return them rather than assume the field exists."""
    older_build = {"visit_type_id": "100010000000032073", "visit_type": "NewPatient-Tele-Health"}
    fake = _FakeAPIClient(pages=[_page([older_build])])
    _patch_client(monkeypatch, fake)

    result = await core_tools.getPracticeInfo.fn(info_type="visit_types")

    assert result["visit_type_count"] == 1
    assert "chart_templates" not in result["visit_types"][0]
    assert "0 of 1 visit type(s)" in result["guidance"]
