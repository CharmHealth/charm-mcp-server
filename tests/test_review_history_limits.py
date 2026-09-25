"""reviewPatientHistory's payload ceiling.

A demo patient with ~1200 encounters serialised past a 200K context window
and killed the turn with Bedrock's "Input is too long for requested model".
Encounters were already bounded (the /encounters read sends per_page); vitals
were not — /patients/{id}/vitals takes no pagination parameters at all, so
every entry came back and went into the model's context verbatim.

These pin the ceiling and, just as importantly, that a truncated response
says so — a chart summary that silently drops history reads as a complete
record.
"""

from __future__ import annotations

import pytest

from tools import patient_management


class _FakeAPIClient:
    def __init__(self, responses):
        self._responses = responses
        self.calls: list[tuple[str, dict | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, endpoint, params=None):
        self.calls.append((endpoint, params))
        return self._responses.get(endpoint, {})


def _patch(monkeypatch, fake):
    monkeypatch.setattr(
        patient_management, "CharmHealthAPIClient", lambda **kwargs: fake
    )


def _responses(n_vitals: int, n_encounters: int, has_more_page: str = "false"):
    return {
        "/patients/p1": {"patient": {"patient_id": "p1", "first_name": "A", "last_name": "B"}},
        "/patients/p1/vitals": {"vital_entries": [
            {"vital_entry_id": f"v{i}", "entry_date": f"2026-07-{(i % 28) + 1:02d} 10:00:00.0",
             "vitals": [{"vital_name": "Weight", "vital_value": "70"}]}
            for i in range(n_vitals)
        ]},
        "/encounters": {
            "encounters": [{"encounter_id": f"e{i}", "date": "2026-07-01"} for i in range(n_encounters)],
            "page_context": {"has_more_page": has_more_page},
        },
        "/patients/p1/medications": {"medications": []},
        "/patients/p1/supplements": {"supplements": []},
        "/patients/p1/allergies": {"allergies": []},
        "/patients/p1/diagnoses": {"diagnoses": []},
    }


async def _review(monkeypatch, fake, **kwargs):
    _patch(monkeypatch, fake)
    return await patient_management.reviewPatientHistory.fn(patient_id="p1", **kwargs)


@pytest.mark.asyncio
async def test_vitals_are_capped_by_default(monkeypatch) -> None:
    """The bug: a caller that names no limit used to get every entry."""
    fake = _FakeAPIClient(_responses(n_vitals=1200, n_encounters=5))

    result = await _review(monkeypatch, fake)

    assert len(result["recent_vitals"]) == 20
    assert result["recent_vitals_has_more"] is True


@pytest.mark.asyncio
async def test_truncated_vitals_are_declared_not_silent(monkeypatch) -> None:
    fake = _FakeAPIClient(_responses(n_vitals=1200, n_encounters=5))

    result = await _review(monkeypatch, fake)

    # The count of what exists survives, so "20 of 1200" is reconstructable.
    assert result["recent_vitals_total_count"] == 1200


@pytest.mark.asyncio
async def test_short_history_is_not_marked_truncated(monkeypatch) -> None:
    fake = _FakeAPIClient(_responses(n_vitals=3, n_encounters=2))

    result = await _review(monkeypatch, fake)

    assert len(result["recent_vitals"]) == 3
    assert result["recent_vitals_has_more"] is False


@pytest.mark.asyncio
async def test_encounters_default_bounds_the_fetch_itself(monkeypatch) -> None:
    """Encounters were never the unbounded section — the read sends per_page.
    The default just makes that explicit rather than accidental."""
    fake = _FakeAPIClient(_responses(n_vitals=5, n_encounters=10))

    await _review(monkeypatch, fake)

    enc_call = next(p for e, p in fake.calls if e == "/encounters")
    assert enc_call["per_page"] == 10
    assert enc_call["sort_order"] == "D"


@pytest.mark.asyncio
async def test_more_encounters_than_one_page_is_declared(monkeypatch) -> None:
    fake = _FakeAPIClient(_responses(n_vitals=5, n_encounters=10, has_more_page="true"))

    result = await _review(monkeypatch, fake)

    assert result["recent_encounters_has_more"] is True


@pytest.mark.asyncio
async def test_explicit_limits_still_win(monkeypatch) -> None:
    """CharmAnywhere sends its own values at its tool-call chokepoint; the
    defaults must not override a caller that knows its context budget."""
    fake = _FakeAPIClient(_responses(n_vitals=1200, n_encounters=50))

    result = await _review(monkeypatch, fake, vitals_limit=5, encounters_limit=30)

    assert len(result["recent_vitals"]) == 5
    enc_call = next(p for e, p in fake.calls if e == "/encounters")
    assert enc_call["per_page"] == 30


# ── Ceilings (PR #25 review) ───────────────────────────────────────────
#
# The defaults only protected callers that omit the argument. A caller
# passing encounters_limit=1200 sent per_page=1200 and reproduced the exact
# context-window failure this change exists to stop. The ceilings match the
# clamp CharmAnywhere applies at its own chokepoint: 50 encounters, 30 vitals.


@pytest.mark.asyncio
async def test_huge_vitals_limit_is_capped(monkeypatch) -> None:
    fake = _FakeAPIClient(_responses(n_vitals=1200, n_encounters=5))

    result = await _review(monkeypatch, fake, vitals_limit=1200)

    assert len(result["recent_vitals"]) == 30
    assert result["recent_vitals_has_more"] is True


@pytest.mark.asyncio
async def test_huge_encounters_limit_is_capped_at_the_request(monkeypatch) -> None:
    fake = _FakeAPIClient(_responses(n_vitals=5, n_encounters=50, has_more_page="true"))

    result = await _review(monkeypatch, fake, encounters_limit=1200)

    enc_call = next(p for e, p in fake.calls if e == "/encounters")
    assert enc_call["per_page"] == 50
    assert result["recent_encounters_has_more"] is True


@pytest.mark.asyncio
async def test_explicit_none_means_the_ceiling_not_unbounded(monkeypatch) -> None:
    """None used to mean "return everything"."""
    fake = _FakeAPIClient(_responses(n_vitals=1200, n_encounters=5))

    result = await _review(monkeypatch, fake, vitals_limit=None, encounters_limit=None)

    assert len(result["recent_vitals"]) == 30
    enc_call = next(p for e, p in fake.calls if e == "/encounters")
    assert enc_call["per_page"] == 50


@pytest.mark.asyncio
async def test_small_encounters_limit_declares_the_rows_it_drops(monkeypatch) -> None:
    """encounters_limit=5 still fetches 10. With 8 encounters the API says
    there are no more pages, but the slice drops 3 — has_more must say so."""
    fake = _FakeAPIClient(_responses(n_vitals=5, n_encounters=8, has_more_page="false"))

    result = await _review(monkeypatch, fake, encounters_limit=5)

    assert len(result["recent_encounters"]) == 5
    assert result["recent_encounters_has_more"] is True


@pytest.mark.asyncio
async def test_exact_fit_is_not_marked_truncated(monkeypatch) -> None:
    fake = _FakeAPIClient(_responses(n_vitals=5, n_encounters=5, has_more_page="false"))

    result = await _review(monkeypatch, fake, encounters_limit=5)

    assert len(result["recent_encounters"]) == 5
    assert result["recent_encounters_has_more"] is False
