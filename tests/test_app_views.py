"""Tests for the MCP App views in common/app_views.py.

These views are what an MCP App client renders. Two properties matter for every
one of them, and both are easy to break while editing a column list:

1. **An empty or partial response must not raise.** Views run inside a tool
   call, so a KeyError here turns a successful clinical read into a failed one.
   Field names also vary across CharmHealth endpoints for the same concept, so
   every column reads a list of candidate keys.
2. **`app_result` must keep the JSON in `content`.** That block is what cortex
   (`mcp/connector.py`) and NoEHR's ToolResponseRegistry read. See
   tests/test_wire_contract.py for the end-to-end version of this.
"""

from __future__ import annotations

import json

import pytest

from common import app_views
from common.app_views import _VIEWS, app_result

# One realistic payload per registered widget type, using the response keys the
# tools actually emit.
PAYLOADS = {
    "patient_list": {"patients": [{"patient_name": "Stan R.", "record_id": "123456"}]},
    "appointment_list": {"appointments": [{"start_time": "09:00", "patient_name": "Stan R."}]},
    "medication_list": {"medications": [{"trade_name": "Sertraline", "strength_description": "100 mg",
                                        "doseform_description": "Tablet", "route_description": "Oral",
                                        "directions": "1 tablet daily", "is_active": "true",
                                        "start_date": "2026-04-22", "dispense": "30",
                                        "dispense_unit": "tablets"}]},
    "supplement_list": {"supplements": [{"supplement_name": "Vitamin D3"}]},
    "allergy_list": {"allergies": [{"allergen": "Penicillin", "severity": "Severe", "status": "Active",
                                   "reactions": ["Hives", "Swelling"], "observed_on": "2024-03-11",
                                   "type": "Drug"}]},
    "diagnosis_list": {"diagnoses": [{"name": "Insomnia", "code": "G47.00"}]},
    "vitals_list": {"vital_entries": [{"entry_date": "2026-08-01", "vital_name": "BP"}]},
    "lab_list": {"lab_results": [{"test_names": ["Hemoglobin A1c"], "result_status": "Abnormal",
                                 "interpretation": "Above reference range",
                                 "reported_date": "2026-04-22", "lab_name": "Quest"}]},
    "recall_list": {"recalls": [{"recall_name": "Annual", "due_date": "2026-12-01"}]},
    "note_list": {"quick_notes": [{"note": "Sleep improving", "date": "2026-08-02"}]},
    "task_list": {"tasks": [{"task": "Call patient re: labs", "status": "In-progress",
                            "priority": "High", "due_date": "2026-09-05",
                            "comments": "Discuss A1c", "owner": {"full_name": "Dr Smith"}}]},
    "encounter_list": {"encounters": [{"date": "2026-04-22", "visit_name": "Follow-up"}]},
    "facility_list": {"facilities": [{"facility_name": "Main Clinic", "city": "SF"}]},
    "provider_list": {"providers": [{"provider_name": "Dr Smith"}]},
    "patient_detail": {"patient": {"full_name": "Stan R.", "record_id": "123456"}},
    "appointment_detail": {"appointment": {"patient_name": "Stan R.", "start_time": "09:00"}},
    "encounter_detail": {"encounter_details": {"encounter_info": {"visit_name": "Follow-up"}}},
    "lab_detail": {"result_report": {"test_name": "A1c",
                                     "results": [{"test_name": "A1c", "result": "5.6", "unit": "%"}]}},
    "patient_history": {"demographics": {"full_name": "Stan R."},
                        "diagnoses": [{"name": "Insomnia"}]},
}


def test_every_registered_widget_type_has_a_test_payload() -> None:
    """A new view without a payload here would go untested silently."""
    assert set(_VIEWS) == set(PAYLOADS), set(_VIEWS) ^ set(PAYLOADS)


@pytest.mark.parametrize("widget_type", sorted(PAYLOADS))
def test_view_builds_from_a_realistic_payload(widget_type: str) -> None:
    view = _VIEWS[widget_type](PAYLOADS[widget_type])
    assert view is not None


@pytest.mark.parametrize("widget_type", sorted(PAYLOADS))
@pytest.mark.parametrize("payload", [{}, {"unexpected": None}, {"appointments": []}])
def test_view_survives_an_empty_or_unexpected_payload(widget_type: str, payload: dict) -> None:
    """A missing section means "not returned", not "none recorded" — the view
    has to render something rather than raise."""
    assert _VIEWS[widget_type](dict(payload)) is not None


@pytest.mark.parametrize("widget_type", sorted(PAYLOADS))
def test_app_result_keeps_the_json_payload(widget_type: str) -> None:
    payload = PAYLOADS[widget_type]
    result = app_result(payload, widget_type)

    assert json.loads(result.content[0].text) == json.loads(json.dumps(payload, default=str))
    assert "$prefab" in result.structured_content


def test_app_result_degrades_when_no_view_is_registered(caplog) -> None:
    """A tool naming a widget type with no view should keep working on plain
    data rather than failing a clinical read."""
    payload = {"something": 1}

    assert app_result(payload, "not_a_widget_type") is payload
    assert "not_a_widget_type" in caplog.text


def test_list_view_hides_search_and_pagination_on_short_lists() -> None:
    """Chrome that helps on a full clinic day is noise on three rows."""
    short = app_views.patient_list_view({"patients": [{"patient_name": "A"}]})
    long = app_views.patient_list_view({"patients": [{"patient_name": str(i)} for i in range(30)]})

    assert short.search is False and short.paginated is False
    assert long.search is True and long.paginated is True


# A real reviewPatientHistory response, trimmed. Kept verbatim in shape because
# the bug it pins was a *structural* miss: `recent_vitals` is a list of entries
# each holding its own `vitals` list, so a flat name lookup found nothing and the
# card announced "No clinical detail" for a patient with seven vitals entries.
REAL_PATIENT_HISTORY = {
    "patient_id": "1995529000000147021",
    "demographics": {
        "record_id": "PAT0002", "full_name": "Hulk Ketchum",
        "dob": "2026-07-01", "gender": "male",
    },
    "current_medications": [], "current_supplements": [], "allergies": [],
    "diagnoses": [], "recent_encounters": [], "upcoming_appointments": [],
    "recent_vitals": [
        {"entry_date": "2026-07-29 16:13:00.0", "vitals": [
            {"vital_name": "Weight", "vital_value": "30.0", "vital_unit": "lbs"},
            {"vital_name": "Height", "vital_value": "12.0", "vital_unit": "ft"},
            {"vital_name": "BMI", "vital_value": "1.02"},
        ]},
        {"entry_date": "2026-07-27 00:00:00.0", "vitals": [
            {"vital_name": "Amphetamines", "vital_value": "Pos (+)"},
        ]},
        {"entry_date": "2026-07-26 00:00:00.0", "vitals": [
            {"vital_name": "Amphetamines", "vital_value": "Neg (-)"},
        ]},
    ],
}


def test_patient_summary_renders_vitals_from_a_real_response() -> None:
    blob = json.dumps(app_result(REAL_PATIENT_HISTORY, "patient_history").structured_content)

    assert "Recent vitals" in blob
    assert "Weight: 30.0 lbs" in blob
    assert "BMI: 1.02" in blob
    # Newest reading per vital wins; the older Amphetamines results are repeats.
    assert "Amphetamines: Pos (+)" in blob
    assert "Amphetamines: Neg (-)" not in blob


def test_patient_summary_does_not_claim_empty_when_a_section_rendered() -> None:
    """The card said "No clinical detail" while showing seven vitals entries,
    because the emptiness check listed keys by hand instead of asking whether
    anything actually rendered."""
    blob = json.dumps(app_result(REAL_PATIENT_HISTORY, "patient_history").structured_content)

    assert "No clinical detail" not in blob


def test_patient_summary_still_says_empty_when_nothing_rendered() -> None:
    blob = json.dumps(
        app_result({"demographics": {"full_name": "Stan R."}}, "patient_history").structured_content
    )

    assert "No clinical detail" in blob


def test_empty_sections_are_omitted_rather_than_shown_empty() -> None:
    """A heading with nothing under it reads as "none recorded" on a clinical
    summary, which may be false — omit it instead."""
    # Inspect the serialized wire form rather than the component object:
    # `model_dump_json` on a Prefab component only dumps its own fields, not
    # its children, so it would pass whatever the tree contains.
    with_allergies = json.dumps(
        app_result(
            {"demographics": {"full_name": "Stan R."}, "allergies": [{"allergen": "Latex"}]},
            "patient_history",
        ).structured_content
    )
    without = json.dumps(
        app_result({"demographics": {"full_name": "Stan R."}}, "patient_history").structured_content
    )

    assert "Latex" in with_allergies
    assert "Allergies" in with_allergies
    assert "Allergies" not in without


# ── Detail parity with NoEHR's list widgets ───────────────────────────


@pytest.mark.parametrize(
    "widget_type,expected",
    [
        ("medication_list", ["Sertraline", "Active", "100 mg", "Oral", "1 tablet daily", "30 tablets"]),
        ("allergy_list", ["Penicillin", "Severe", "Hives", "Drug", "11 Mar 2024"]),
        ("lab_list", ["Hemoglobin A1c", "Abnormal", "Above reference range", "Quest"]),
        ("task_list", ["Call patient re: labs", "In-progress", "High priority", "Dr Smith", "Discuss A1c"]),
    ],
)
def test_clinical_lists_render_the_fields_noehr_shows(widget_type: str, expected: list) -> None:
    """A four-column table dropped most of what these rows carry. The field sets
    come from NoEHR's typed models, so a regression here means the card is
    quietly showing a clinician less than the app does."""
    blob = json.dumps(app_result(PAYLOADS[widget_type], widget_type).structured_content)

    missing = [field for field in expected if field not in blob]
    assert not missing, f"{widget_type} dropped {missing}"


def test_status_badges_pick_a_variant_from_the_text() -> None:
    """Colour reads as clinical meaning, so an unrecognised status must stay
    neutral rather than being guessed into a severity."""
    assert app_views._badge_variant("Severe") == "destructive"
    assert app_views._badge_variant("Active") == "success"
    assert app_views._badge_variant("Moderate") == "warning"
    assert app_views._badge_variant("Something we have never seen") == "outline"


def test_vitals_list_reads_readings_nested_inside_entries() -> None:
    blob = json.dumps(
        app_result({"vital_entries": [{"entry_date": "2026-07-29", "vitals": [
            {"vital_name": "Weight", "vital_value": "30.0", "vital_unit": "lbs"}]}]},
            "vitals_list").structured_content
    )

    assert "Weight: 30.0 lbs" in blob


# ── Dates ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-07-22 15:01:00", "22 Jul 2026 · 3:01pm"),
        # A midnight time is the API saying "no time recorded" — rendering
        # "00:00:00" states something the record does not.
        ("2026-05-04 00:00:00", "4 May 2026"),
        ("2026-07-29 16:13:00.0", "29 Jul 2026 · 4:13pm"),
        ("2026-07-01", "1 Jul 2026"),
        ("2026-09-16 09:00:00", "16 Sep 2026 · 9:00am"),
        # Epoch milliseconds — task due dates and last_modified_time arrive this
        # way. Date only: the value is midnight in the practice's timezone, so a
        # UTC clock reading would invent a "7:00am" the record never stated.
        ("1789023600000", "10 Sep 2026"),
        ("1787266571009", "20 Aug 2026"),
        # Not timestamps: 8 digits is a bare date, 10 would be seconds.
        ("20260722", "20260722"),
        ("1789023600", "1789023600"),
        # Anything unparseable is passed through rather than mangled.
        ("sometime last spring", "sometime last spring"),
        ("", ""),
    ],
)
def test_dates_render_readably(raw: str, expected: str) -> None:
    assert app_views._fmt_date(raw) == expected


def test_patient_summary_formats_dates_and_omits_missing_parts() -> None:
    """Regression: `_fmt_date` shipped without its `re` import and 212 tests
    passed, because nothing drove a date string through a rendered card."""
    blob = json.dumps(app_result({
        "demographics": {"full_name": "Dummy Patient"},
        "recent_encounters": [
            {"date": "2026-07-22 15:01:00", "visit_name": "Follow-up Visit",
             "physician_name": "Dr Smith"},
            {"date": "2026-05-04 00:00:00"},
        ],
    }, "patient_history").structured_content, ensure_ascii=False)

    assert "22 Jul 2026 · 3:01pm · Follow-up Visit · Dr Smith" in blob
    # A record with no visit name renders as a date, not a date and a stray dash.
    assert "4 May 2026" in blob
    assert "00:00:00" not in blob
    assert "4 May 2026 ·" not in blob


def test_long_sections_are_capped_with_a_count() -> None:
    """A summary listing every encounter back to 2013 buries the recent ones."""
    blob = json.dumps(app_result({
        "demographics": {"full_name": "Dummy Patient"},
        "recent_encounters": [{"date": f"2026-0{i}-01", "visit_name": f"Visit {i}"}
                              for i in range(1, 9)],
    }, "patient_history").structured_content)

    assert "+2 more" in blob


# ── Field names taken from the shipped app, not inferred ──────────────

# The raw shape of GET /patients/{id}/medications, which reviewPatientHistory
# passes through untouched. None of these records carries "drug_name" or "name",
# which is what the summary card used to look for — so it rendered "• —" per
# medication while the JSON held all three.
RAW_MEDICATIONS = {
    "demographics": {"full_name": "Dummy Patient"},
    "current_medications": [
        {"trade_name": "Zoloft", "generic_drug_name": "sertraline",
         "strength_description": "100 mg", "is_active": "true"},
        {"generic_product_name": "metformin HCl", "strength_description": "500 mg",
         "is_active": "1"},
        {"generic_drug_name": "lisinopril"},
    ],
    "current_supplements": [
        {"supplement_name": "Vitamin D3", "strength": "1000 IU", "status": "1"},
    ],
}


def test_summary_names_medications_from_the_raw_record() -> None:
    """Priority is NoEHR's: tradeName ?? genericProductName ?? genericDrugName."""
    blob = json.dumps(app_result(RAW_MEDICATIONS, "patient_history").structured_content,
                      ensure_ascii=False)

    assert "Zoloft · 100 mg" in blob
    assert "metformin HCl · 500 mg" in blob
    assert "lisinopril" in blob


def test_no_section_ever_renders_a_placeholder_row() -> None:
    """A bullet reading "—" says a medication exists but not which one, which is
    worse than omitting it. Unnameable records are dropped and stay in the JSON."""
    result = app_result(
        {"demographics": {"full_name": "Dummy Patient"},
         "current_medications": [{"patient_medication_id": "m1"}, {"trade_name": "Zoloft"}]},
        "patient_history",
    )
    blob = json.dumps(result.structured_content, ensure_ascii=False)

    # A dash inside a labelled Metric ("MRN —") reads as "not recorded" and is
    # fine. A dash as a bullet does not — that is the case being pinned.
    assert "• —" not in blob
    assert "Zoloft" in blob
    # The unnameable record is still in the payload the model reads.
    assert "m1" in result.content[0].text


def test_supplement_status_is_decoded_from_its_numeric_flag() -> None:
    """Supplements report status as "1"/"0"; a badge reading "1" says nothing."""
    blob = json.dumps(app_result(RAW_MEDICATIONS, "supplement_list").structured_content,
                      ensure_ascii=False)

    assert "Active" in blob
    assert '"label": "1"' not in blob


@pytest.mark.parametrize(
    "raw,expected",
    [("1", "Active"), ("0", "Inactive"), ("true", "Active"), ("false", "Inactive"),
     ("Active", "Active"), ("Resolved", "Resolved"),
     # A number we cannot name is not a status — better absent than shown.
     ("7", ""), ("", "")],
)
def test_numeric_status_flags_are_decoded_or_dropped(raw: str, expected: str) -> None:
    assert app_views._decode_status(raw) == expected


def test_allergy_shows_severity_and_a_readable_status() -> None:
    """Screenshot regression: the meta line read "Medication · 1" — the numeric
    status flag, included by an inverted condition that added it *because*
    severity was present."""
    blob = json.dumps(app_result(
        {"allergies": [{"allergen": "procaine penicillin", "severity": "Severe",
                        "type": "Medication", "status": "1", "reactions": ["Rash"]}]},
        "allergy_list").structured_content, ensure_ascii=False)

    assert "Severe" in blob
    assert "Medication · Active" in blob
    assert "Medication · 1" not in blob


def test_allergy_status_chip_is_dropped_when_it_repeats_the_badge() -> None:
    blob = json.dumps(app_result(
        {"allergies": [{"allergen": "Latex", "severity": "Active", "status": "1"}]},
        "allergy_list").structured_content, ensure_ascii=False)

    assert blob.count("Active") == 1


def test_task_priority_is_decoded_from_its_numeric_code() -> None:
    """Screenshot regression: cards read "0 priority", which is meaningless and
    reads as "no priority" when 0 means Low. Mapping is NoEHR's
    `TaskItem.priorityLabel`."""
    blob = json.dumps(app_result({"tasks": [
        {"task": "Reconcile supplement list", "status": "Completed",
         "due_date": "1789023600000", "priority": "0",
         "owner": {"full_name": "Jerry Liang"}},
        {"task": "Call patient", "status": "In-progress",
         "due_date": "1788850800000", "priority": "2"},
    ]}, "task_list").structured_content, ensure_ascii=False)

    assert "Low priority" in blob and "High priority" in blob
    assert "0 priority" not in blob and "2 priority" not in blob
    # And the due dates are dates, not raw epoch milliseconds.
    assert "Due 10 Sep 2026" in blob
    assert "1789023600000" not in blob


@pytest.mark.parametrize("code,label", [("0", "Low"), ("1", "Medium"), ("2", "High"),
                                        ("3", "Critical"), ("Urgent", "Urgent"), ("", "")])
def test_task_priority_mapping(code: str, label: str) -> None:
    assert app_views._task_priority(code) == label


# ── Nothing renders a record it cannot identify ───────────────────────

# A record carrying only its own id is the realistic minimum a list can return.
MINIMAL_RECORDS = {
    "patient_list": {"patients": [{"patient_id": "1"}]},
    "appointment_list": {"appointments": [{"appointment_id": "1"}]},
    "medication_list": {"medications": [{"patient_medication_id": "1"}]},
    "supplement_list": {"supplements": [{"patient_supplement_id": "1"}]},
    "allergy_list": {"allergies": [{"patient_allergy_id": "1"}]},
    "diagnosis_list": {"diagnoses": [{"patient_diagnosis_id": "1"}]},
    "vitals_list": {"vital_entries": [{"vital_entry_id": "1"}]},
    "lab_list": {"lab_results": [{"group_id": "1"}]},
    "recall_list": {"recalls": [{"recall_id": "1"}]},
    "note_list": {"quick_notes": [{"quick_notes_id": "1"}]},
    "task_list": {"tasks": [{"task_id": "1"}]},
    "encounter_list": {"encounters": [{"encounter_id": "1"}]},
    "facility_list": {"facilities": [{"facility_id": "1"}]},
    "provider_list": {"providers": [{"member_id": "1"}]},
}


@pytest.mark.parametrize("widget_type", sorted(MINIMAL_RECORDS))
def test_unidentifiable_records_render_nothing(widget_type: str) -> None:
    """The quick-notes card drew a block containing a single em-dash, because
    every field was looked up under the wrong name and the title fell through to
    the placeholder. A card that asserts a record exists while showing none of it
    is worse than an empty state — this pins every list against that."""
    result = app_result(MINIMAL_RECORDS[widget_type], widget_type)
    blob = json.dumps(result.structured_content, ensure_ascii=False)

    assert "• —" not in blob
    # Tables: a row of nothing but placeholders is dropped entirely. A dash in
    # *some* cells is fine, since a missing phone number is a fact.
    rows = result.structured_content.get("view", {})
    assert '"Patient": "—", "MRN": "—"' not in blob
    # The record is still in the JSON the model reads.
    assert "1" in result.content[0].text


def test_table_keeps_rows_that_are_only_partly_populated() -> None:
    result = app_result(
        {"patients": [{"patient_id": "1"}, {"full_name": "Stan R.", "record_id": "PAT1"}]},
        "patient_list",
    )
    blob = json.dumps(result.structured_content, ensure_ascii=False)

    assert "Stan R." in blob
    # One identifiable row, not two.
    assert blob.count("PAT1") == 1


def test_quick_notes_render_their_text_and_date() -> None:
    """The real managePatientNotes response: the field is `notes`, plural, and
    the only date is `last_modified_time` in epoch milliseconds."""
    blob = json.dumps(app_result({"quick_notes": [
        {"quick_notes_id": "1995529000000094015", "last_modified_time": 1759334015919,
         "last_modified_by": "1995529000000021021", "notes": "Hi"},
    ]}, "note_list").structured_content, ensure_ascii=False)

    assert "Hi" in blob
    assert "1 Oct 2025" in blob
