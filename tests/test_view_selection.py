"""A tool's App view is chosen from the case that ran, never from the payload.

The payload's keys are ambiguous. providers_by_privilege returns "providers"
just as providers does, overview returns facilities and providers together,
and strip_empty_values deletes an empty list before anything can inspect it.
Each of those once picked the wrong view: an empty provider table for vitals,
"No medications on the chart." for a patient with no supplements.
"""

from __future__ import annotations

import json

import pytest

from tools import clinical_data, core_tools


class _FakeAPIClient:
    def __init__(self, get_responses):
        self._get = get_responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        return self._get[endpoint]


_PRACTICE = {
    "/facilities": {"facilities": [{"facility_id": "f1", "facility_name": "Main"}]},
    "/members": {"members": [{"member_id": "m1", "full_name": "Alex Doe"}],
                 "page_context": {"has_more_page": False}},
    "/vitals/metrics": {"vitals": [{"vital_name": "Weight"}]},
    "/templates": {"templates": [{"template_id": "t1", "template_name": "SOAP"}]},
}


def _rendered(result) -> str:
    return json.dumps(result.structured_content)


@pytest.mark.asyncio
@pytest.mark.parametrize("info_type", ["facilities", "providers"])
async def test_directory_info_types_get_their_own_view(monkeypatch, info_type) -> None:
    monkeypatch.setattr(core_tools, "CharmHealthAPIClient", lambda **kw: _FakeAPIClient(_PRACTICE))

    result = await core_tools.getPracticeInfo(info_type=info_type)

    assert result.structured_content is not None
    assert json.loads(result.content[0].text)[info_type]


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"info_type": "vitals"},
    {"info_type": "templates"},
    {"info_type": "overview"},
    {"info_type": "providers_by_privilege", "privilege": "sign_encounter"},
])
async def test_info_types_without_a_shared_widget_return_plain_json(monkeypatch, kwargs) -> None:
    # overview carries facilities, and providers_by_privilege carries
    # "providers", so a key-based choice drew a directory table for both.
    monkeypatch.setattr(core_tools, "CharmHealthAPIClient", lambda **kw: _FakeAPIClient(_PRACTICE))

    result = await core_tools.getPracticeInfo(**kwargs)

    assert isinstance(result, dict)
    assert "error" not in result


@pytest.mark.asyncio
async def test_a_patient_with_no_supplements_gets_the_supplement_view(monkeypatch) -> None:
    fake = _FakeAPIClient({"/patients/p1/supplements": {"supplements": []}})
    monkeypatch.setattr(clinical_data, "CharmHealthAPIClient", lambda **kw: fake)

    result = await clinical_data.managePatientDrugs(
        action="list", patient_id="p1", substance_type="supplement",
    )

    assert "No supplements on the chart." in _rendered(result)
    assert "No medications on the chart." not in _rendered(result)
