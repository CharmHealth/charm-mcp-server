"""MCP App views — the interactive UI a tool returns alongside its JSON.

Deliberately not named for any one client. MCP Apps was chosen over a
client-specific layout format precisely because a Prefab component tree is not
tied to one renderer, and a filename is part of keeping that true.

**The contract every caller must hold to.** A tool must never return a bare
component. FastMCP renders that as
``content=[TextContent(text="[Rendered Prefab UI]")]`` with the component tree in
``structured_content`` — which strips the JSON that cortex reads (it joins the
text content blocks and runs ``json.loads``) and that NoEHR's
``ToolResponseRegistry`` decodes. Always build the result explicitly:

    return ToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structured_content=appointment_list_view(data),
    )

``tests/test_wire_contract.py`` fails loudly if that discipline slips.

View names mirror cortex's widget types in `runtime/widgets.py`
(`appointment_list`, `patient_history`), so the same vocabulary describes the
same thing in all three repos.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from prefab_ui.components import (
    Badge,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Column,
    DataTable,
    DataTableColumn,
    Metric,
    Muted,
    Row,
    Separator,
    Text,
)

logger = logging.getLogger(__name__)

__all__ = [
    "app_result",
    # Lists — keyed by the widget type cortex's _LIST_KEY_MAP produces.
    "allergy_list_view",
    "appointment_list_view",
    "diagnosis_list_view",
    "encounter_list_view",
    "facility_list_view",
    "lab_list_view",
    "medication_list_view",
    "note_list_view",
    "patient_list_view",
    "provider_list_view",
    "recall_list_view",
    "supplement_list_view",
    "task_list_view",
    "vitals_list_view",
    # Details
    "appointment_detail_view",
    "encounter_detail_view",
    "lab_detail_view",
    "patient_detail_view",
    "patient_summary_view",
]


def _first(source: Dict[str, Any], *keys: str, default: str = "—") -> str:
    """First present, non-empty value among *keys*.

    Field names vary across CharmHealth endpoints (a provider is
    `member_name` on one response and `physician_name` on another), so views
    read a list of candidates rather than one name.
    """
    for key in keys:
        value = source.get(key)
        if value not in (None, "", []):
            return str(value)
    return default


def _time_of_day(appt: Dict[str, Any]) -> str:
    """Appointment time, which is not a field of its own.

    The API returns `appointment_date` as "2026-09-10 09:00:00" and the time is
    the part after the space — NoEHR's `AppointmentItem.displayTime` reads it the
    same way, falling back to `appointment_start_time_utc` in epoch
    milliseconds. Looking for a `start_time` key finds nothing, which is why this
    column rendered as a dash for every row.
    """
    raw = str(_first(appt, "appointment_date", "date", default="")).strip()
    if " " in raw:
        clock = raw.split(" ", 1)[1]
        m = re.match(r"^(\d{1,2}):(\d{2})", clock)
        if m:
            hour, minute = int(m.group(1)), m.group(2)
            suffix = "am" if hour < 12 else "pm"
            return f"{hour % 12 or 12}:{minute}{suffix}"

    utc = str(_first(appt, "appointment_start_time_utc", default="")).strip()
    if utc.isdigit() and 12 <= len(utc) <= 14:
        try:
            stamp = datetime.fromtimestamp(int(utc) / 1000, tz=timezone.utc)
            return f"{stamp.hour % 12 or 12}:{stamp.minute:02d}{'am' if stamp.hour < 12 else 'pm'}"
        except (ValueError, OSError, OverflowError):
            pass

    # Some responses carry a bare clock field instead.
    return _first(appt, "start_time", "appointment_time", "from_time", default="")


def appointment_list_view(data: Dict[str, Any]) -> DataTable:
    """The schedule. Stays a table — it is genuinely tabular and time-ordered —
    but carries the fields NoEHR's AppointmentListWidget shows: status, visit
    type, mode and duration, not just a time and a name."""
    appointments: List[Dict[str, Any]] = data.get("appointments") or []
    rows = []
    for appt in appointments:
        if not isinstance(appt, dict):
            continue
        row = {
            "Time": _time_of_day(appt) or "—",
            "Patient": _first(appt, "patient_name", "full_name"),
            "Reason": _first(appt, "reason_for_appointment", "reason", "visit_type",
                             "appointment_type"),
            "Provider": _first(appt, "provider_name", "member_name", "physician_name"),
            "Status": _status_of(appt, "appointment_status", "status"),
            "Mode": _first(appt, "appointment_mode", "mode"),
        }
        if any(value not in ("—", "") for value in row.values()):
            rows.append(row)
    return DataTable(
        columns=[
            DataTableColumn(key="Time", header="Time", width="90px"),
            DataTableColumn(key="Patient", header="Patient", sortable=True),
            DataTableColumn(key="Reason", header="Reason"),
            DataTableColumn(key="Provider", header="Provider", sortable=True),
            DataTableColumn(key="Status", header="Status", sortable=True),
            DataTableColumn(key="Mode", header="Mode"),
        ],
        rows=rows,
        # Searching a short day is noise; searching a full clinic day is not.
        search=len(rows) > 8,
        paginated=len(rows) > 25,
    )


# Name candidates per entity, in priority order. Shared by the summary card and
# the list views so the two cannot drift — a summary that looked for
# "drug_name"/"name" while the API returns trade_name/generic_drug_name is how
# the medications section came to render three bullets of "—".
# Priority copied from the shipped app, not inferred: NoEHR's
# `MedicationItem.displayName` is tradeName ?? genericProductName ??
# genericDrugName (WidgetModels.swift:347), and SupplementItem.displayName is
# supplementName ?? genericSupplementName. `drug_name` leads because
# managePatientDrugs adds it as a canonical field (J13/CH-695); reviewPatientHistory
# returns the raw record, which has none of the three names this used to look for.
_MED_NAME_KEYS = ("drug_name", "trade_name", "generic_product_name",
                  "generic_drug_name", "medication_name", "name")
_SUPPLEMENT_NAME_KEYS = ("supplement_name", "generic_supplement_name", "drug_name", "name")
_ALLERGEN_KEYS = ("allergen", "allergy_name", "drug_name", "name")
_DIAGNOSIS_NAME_KEYS = ("diagnosis_name", "name", "description")

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fmt_date(value: Any) -> str:
    """Readable date from the several shapes CharmHealth returns.

    Endpoints hand back "2026-07-22", "2026-07-22 15:01:00" and
    "2026-07-29 16:13:00.0" for the same idea. A midnight time is the API's way
    of saying "no time recorded", so showing "00:00:00" states something the
    record does not — it gets dropped rather than rendered.
    """
    text = str(value or "").strip()
    # Epoch milliseconds: task due dates and `last_modified_time` arrive this
    # way, and NoEHR divides by 1000 before formatting (WidgetModels.swift:275).
    # 10 digits would be seconds and is out of range for a date this API returns,
    # so only 12-14 digits are treated as a timestamp — a bare "20260722" is not.
    if text.isdigit() and 12 <= len(text) <= 14:
        try:
            stamp = datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc)
            # Date only, deliberately. These are midnight in the practice's own
            # timezone, so a UTC clock reading turns every task due date into
            # "7:00am" — a time the record never stated. NoEHR formats due dates
            # with timeStyle .none for the same reason. The practice timezone is
            # on the patient record but not on the task, so a date read in UTC
            # can still be a day early for practices east of UTC; that is a
            # smaller error than inventing a time.
            text = stamp.strftime("%Y-%m-%d")
        except (ValueError, OSError, OverflowError):
            return text
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", text)
    if not m:
        return text
    year, month, day, hour, minute = m.groups()
    try:
        stamp = f"{int(day)} {_MONTHS[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return text
    if hour is not None and (hour, minute) != ("00", "00"):
        h = int(hour)
        suffix = "am" if h < 12 else "pm"
        display = h % 12 or 12
        stamp += f" · {display}:{minute}{suffix}"
    return stamp


def _section(title: str, items: List[str], limit: int = 6) -> List[Any]:
    """A titled list, or nothing at all when there is nothing to show.

    An empty section is worse than a missing one on a clinical summary: a
    heading with no content reads as "none recorded" when it may only mean
    "not returned by this call".

    Long sections are capped. A summary card listing every encounter back to
    2013 buries the recent ones, which is the opposite of a summary.
    """
    if not items:
        return []
    shown = items[:limit]
    extra = len(items) - len(shown)
    block: List[Any] = [
        Text(content=title, bold=True),
        *[Text(content=f"• {item}") for item in shown],
    ]
    if extra > 0:
        block.append(Muted(content=f"+{extra} more"))
    block.append(Separator(spacing=2))
    return block


def _latest_vitals(entries: List[Any]) -> List[str]:
    """Most recent reading per distinct vital, newest first.

    `reviewPatientHistory` returns `recent_vitals` as a list of *entries*, each
    holding its own list of readings — so a flat name lookup finds nothing. Seven
    entries of the same three metrics is a trend, not a summary, so this keeps
    the newest reading for each name and drops the repeats. Entries arrive
    newest-first, so first occurrence wins.
    """
    seen: Dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for reading in entry.get("vitals") or []:
            if not isinstance(reading, dict):
                continue
            name = reading.get("vital_name")
            if not name or name in seen:
                continue
            value = str(reading.get("vital_value", "")).strip()
            unit = str(reading.get("vital_unit", "")).strip()
            seen[name] = f"{name}: {value} {unit}".strip()
    return list(seen.values())


def patient_summary_view(data: Dict[str, Any]) -> Card:
    """A patient summary card. Mirrors cortex's `patient_history` widget.

    Reads the compound response `reviewPatientHistory` returns, whose sections
    are each independently optional depending on the `include_*` flags. Every
    section that carries data has to appear here — a section this view forgets
    is clinical data silently dropped from the card while the JSON still has it.
    """
    demographics: Dict[str, Any] = data.get("demographics") or data.get("patient") or {}

    name = _first(demographics, "full_name", "patient_name", "first_name", default="Patient")
    identifiers = Row(
        gap=6,
        children=[
            Metric(label="MRN", value=_first(demographics, "record_id", "patient_record_id", "mrn")),
            Metric(label="DOB", value=_first(demographics, "dob", "date_of_birth")),
            Metric(label="Gender", value=_first(demographics, "gender", "sex")),
        ],
    )

    def _names(section: str, keys: tuple, detail_keys: tuple = ()) -> List[str]:
        """Display names for one section, skipping records we can't name.

        `_first` returns an em-dash placeholder when nothing matches, and a
        bullet reading "—" tells a clinician a medication exists but not which
        one — worse than omitting the row. Anything unnameable is dropped here
        and the JSON still carries it.
        """
        lines = []
        for entry in data.get(section) or []:
            if not isinstance(entry, dict):
                continue
            name = _first(entry, *keys, default="")
            if not name:
                continue
            detail = _joined(entry, *detail_keys) if detail_keys else ""
            lines.append(f"{name} · {detail}" if detail else name)
        return lines

    def _dated(section: str, date_keys: tuple, label_keys: tuple,
               meta_keys: tuple = ()) -> List[str]:
        """One line per dated record: when, what, and who.

        Parts that are absent are dropped rather than joined around, so a record
        with no visit name renders as a date instead of a date and a stray dash.
        """
        lines = []
        for entry in data.get(section) or []:
            if not isinstance(entry, dict):
                continue
            parts = [_fmt_date(_first(entry, *date_keys, default=""))]
            what = _first(entry, *label_keys, default="")
            if what:
                parts.append(what)
            who = _first(entry, *meta_keys, default="") if meta_keys else ""
            if who:
                parts.append(who)
            line = " · ".join(part for part in parts if part)
            if line:
                lines.append(line)
        return lines

    sections = [
        ("Active problems", _names("diagnoses", _DIAGNOSIS_NAME_KEYS, ("code", "status"))
         or _names("patient_diagnoses", _DIAGNOSIS_NAME_KEYS, ("code", "status"))),
        ("Current medications",
         _names("current_medications", _MED_NAME_KEYS,
                ("strength_description", "directions", "sig"))
         or _names("medications", _MED_NAME_KEYS,
                   ("strength_description", "directions", "sig"))),
        ("Supplements",
         _names("current_supplements", _SUPPLEMENT_NAME_KEYS, ("strength", "dosage_form"))
         or _names("supplements", _SUPPLEMENT_NAME_KEYS, ("strength", "dosage_form"))),
        ("Allergies", _names("allergies", _ALLERGEN_KEYS, ("severity", "reactions"))
         or _names("patient_allergies", _ALLERGEN_KEYS, ("severity", "reactions"))),
        ("Recent vitals", _latest_vitals(data.get("recent_vitals") or data.get("vitals") or [])),
        ("Recent encounters",
         _dated("recent_encounters", ("date", "encounter_date"),
                ("visit_name", "encounter_type", "chart_type", "chief_complaints"),
                ("provider_name", "physician_name", "member_name"))
         or _dated("encounters", ("date", "encounter_date"),
                   ("visit_name", "encounter_type", "chart_type", "chief_complaints"),
                   ("provider_name", "physician_name", "member_name"))),
        ("Upcoming appointments",
         _dated("upcoming_appointments", ("appointment_date", "date", "start_time"),
                ("reason_for_appointment", "reason", "visit_type", "appointment_type"),
                ("provider_name", "physician_name", "member_name"))),
    ]

    body: List[Any] = [identifiers, Separator(spacing=2)]
    rendered = 0
    for title, lines in sections:
        block = _section(title, lines)
        body += block
        rendered += bool(block)

    # Only claim there is nothing to show when nothing above rendered. Checking a
    # hand-listed subset of keys is what made this card say "no clinical detail"
    # for a patient with seven vitals entries.
    if not rendered:
        body.append(Muted(content="No clinical detail was returned for this patient."))
    elif isinstance(body[-1], Separator):
        body.pop()  # no rule under the last section

    return Card(
        children=[
            CardHeader(children=[CardTitle(content=name)]),
            CardContent(children=[Column(gap=2, children=body)]),
        ]
    )


_VIEWS: Dict[str, Any] = {}  # populated at the end of this module


def app_result(payload: Dict[str, Any], widget_type: str) -> "ToolResult":
    """Build the tool result for a read that has a view.

    The only sanctioned way to return an MCP App view from a tool. It puts the
    JSON in `content` — which is what cortex reads (`mcp/connector.py` joins the
    text blocks and runs `json.loads`) and what NoEHR's ToolResponseRegistry
    decodes — and the Prefab component in `structured_content`.

    Call sites use this rather than assembling a ToolResult themselves so the
    JSON half cannot be forgotten. Returning a bare component instead makes
    FastMCP substitute the literal "[Rendered Prefab UI]" for the data, which
    breaks both other surfaces without raising anything.

    An unknown `widget_type` returns the plain dict rather than raising: a
    missing view should degrade to today's behaviour, not fail a clinical call.
    """
    from fastmcp.tools import ToolResult
    from mcp_types import TextContent

    # An error payload gets no view and, more importantly, must stay a dict.
    # `@with_tool_metrics()` raises ToolError only for a *dict* carrying an
    # "error" key — a ToolResult slips past that check, so wrapping an error
    # here reported the call as a success with the failure buried in the JSON.
    # cortex's classify_widget returns None for the same input, for the same
    # reason: there is nothing to draw for a failure.
    if isinstance(payload, dict) and "error" in payload:
        return payload

    view_builder = _VIEWS.get(widget_type)
    if view_builder is None:
        logger.warning("No MCP App view registered for %r; returning plain data", widget_type)
        return payload

    return ToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, default=str))],
        structured_content=view_builder(payload),
    )



# ── Record blocks (the clinical lists) ────────────────────────────────
#
# A four-column table loses most of what a clinician reads. NoEHR's list
# widgets render each item as a small stack — name in bold, a status pill, a
# detail line, then dimmer metadata (dates, provider, dispense) — and the
# field inventory below comes from its typed models in
# `Core/Networking/CharmHealthAPIClient/*Models.swift`, not from guesswork.
#
# Tables are kept only where the data really is tabular and scannable: the
# schedule, and the patient/provider/facility directories.

_STATUS_VARIANTS = {
    # status text (lowercased, first match wins) -> Badge variant
    "active": "success",
    "current": "success",
    "completed": "success",
    "signed": "success",
    "resolved": "secondary",
    "inactive": "secondary",
    "discontinued": "secondary",
    "cancelled": "secondary",
    "canceled": "secondary",
    "severe": "destructive",
    "high": "destructive",
    "abnormal": "destructive",
    "critical": "destructive",
    "moderate": "warning",
    "medium": "warning",
    "pending": "warning",
    "in-progress": "warning",
    "in progress": "warning",
    "overdue": "warning",
    "mild": "info",
    "low": "info",
}


def _badge_variant(text: str) -> str:
    """Map a status or severity string to a Badge variant.

    Unknown values get the neutral variant rather than a guess — colouring a
    status we don't recognise is worse than not colouring it, because the colour
    reads as clinical meaning.
    """
    lowered = (text or "").strip().lower()
    for needle, variant in _STATUS_VARIANTS.items():
        if needle in lowered:
            return variant
    return "outline"


def _joined(source: Dict[str, Any], *keys: str, sep: str = " · ") -> str:
    """Non-empty values for `keys`, in order, joined — for a detail line built
    from several optional fields (strength, form, route)."""
    parts = []
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value if v)
        if value not in (None, "", [], "—"):
            parts.append(str(value))
    return sep.join(parts)


def _date_range(source: Dict[str, Any], start_keys: tuple, end_keys: tuple) -> str:
    start = _fmt_date(_first(source, *start_keys, default=""))
    end = _fmt_date(_first(source, *end_keys, default=""))
    if start and end:
        return f"{start} → {end}"
    return start or end


_TASK_PRIORITIES = {"0": "Low", "1": "Medium", "2": "High", "3": "Critical"}


def _task_priority(value: Any) -> str:
    """Readable task priority.

    The wire value is a numeric code, so "0 priority" on a card is meaningless
    and, worse, reads as "no priority" when 0 means Low. Mapping copied from
    NoEHR's `TaskItem.priorityLabel`; anything unrecognised passes through.
    """
    raw = str(value or "").strip()
    return _TASK_PRIORITIES.get(raw, raw)


def _decode_status(value: Any) -> str:
    """A status a clinician can read, or nothing.

    Several endpoints report status as a numeric flag rather than a word:
    supplements use "1"/"0" (NoEHR reads it as `SupplementItem.isCurrentlyActive
    == (status == "1")`) and allergies do the same when `display_status` is
    absent. Rendering the raw value puts a badge or a chip reading "1" on the
    card, which states nothing. Any other bare number is dropped for the same
    reason — a number we cannot name is not a status.
    """
    raw = str(value or "").strip()
    if raw in ("1", "true", "True"):
        return "Active"
    if raw in ("0", "false", "False"):
        return "Inactive"
    return "" if raw.isdigit() else raw


def _status_of(record: Dict[str, Any], *keys: str) -> str:
    """First readable status among `keys`."""
    for key in keys:
        decoded = _decode_status(record.get(key))
        if decoded:
            return decoded
    return ""


def _record_block(title: str, status: str, detail: str, meta: str) -> List[Any]:
    """One item, laid out the way NoEHR lays out a list row.

    A record with neither a title nor a detail renders nothing. The quick-notes
    card drew an empty block containing a single em-dash, because the title fell
    through to `_first`'s placeholder and every other field was looked up under
    the wrong name — a card that asserts a record exists while showing none of it.
    """
    title = "" if title in (None, "—") else str(title).strip()
    if not title and not detail:
        return []
    header: List[Any] = [Text(content=title or detail, bold=True)]
    if not title:
        detail = ""
    if status:
        header.append(Badge(label=status, variant=_badge_variant(status)))
    block: List[Any] = [Row(gap=2, align="center", children=header)]
    if detail:
        block.append(Text(content=detail))
    if meta:
        block.append(Muted(content=meta))
    block.append(Separator(spacing=2))
    return block


def _records_view(items: List[Any], builder, empty_message: str) -> Column:
    blocks: List[Any] = []
    for item in items:
        if isinstance(item, dict):
            blocks += builder(item)
    if not blocks:
        return Column(gap=2, children=[Muted(content=empty_message)])
    return Column(gap=2, children=blocks[:-1])  # drop the trailing separator


def _items(data: Dict[str, Any], *keys: str) -> List[Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list) and value:
            return value
    return []


# ── Lists ─────────────────────────────────────────────────────────────
#
# Every list is the same shape — a table over one array in the response —
# so the per-type differences are data, not code. Each column names the
# candidate response keys to try in order, because field names differ
# across CharmHealth endpoints for the same concept.
#
# One deliberate omission: none of these carry a button. NoEHR's list
# widgets don't either — `ListWidgetShell` takes no action parameter and no
# widget under `Widgets/Lists` dispatches an action. Writes live in its
# detail views, behind `WidgetAction.executeWithConfirmation` or a form
# sheet. See the module note in `_write_affordances_are_deliberately_absent`.

_ColumnSpec = List[tuple]  # (header, (candidate keys...), sortable)

_LIST_SPECS: Dict[str, tuple] = {
    # Directory lists only. The clinical lists are record blocks above — a table
    # cannot carry a status badge or a second line, and that is most of what a
    # clinician reads. These three are genuinely tabular: short rows, scannable,
    # and worth sorting.
    "patient_list": (
        ("patients",),
        [
            ("Patient", ("patient_name", "full_name"), True),
            ("MRN", ("record_id", "patient_record_id", "mrn"), False),
            ("DOB", ("dob", "date_of_birth"), False),
            ("Phone", ("mobile", "home_phone", "phone"), False),
            ("Email", ("email",), False),
        ],
    ),
    # These two carry their identifier, unlike the clinical lists. Their whole
    # purpose is supplying an ID for the *next* call — getPracticeInfo's own
    # guidance says "use facility IDs from this list" and "use provider IDs
    # (member_id) from this list". A rendered list that omits them makes that
    # instruction unfollowable for any caller reading the view rather than the
    # raw JSON, which is how a model came to pass the facility *name* as
    # facility_ids after fetching this list twice.
    "facility_list": (
        ("facilities",),
        [
            ("Facility", ("facility_name", "name"), True),
            ("Facility ID", ("facility_id", "id"), False),
            ("City", ("city",), True),
            ("State", ("state",), False),
            ("Phone", ("phone", "contact_number"), False),
        ],
    ),
    "provider_list": (
        ("providers", "members"),
        [
            ("Provider", ("provider_name", "full_name", "name"), True),
            ("Provider ID", ("member_id", "provider_id", "id"), False),
            ("Speciality", ("speciality", "specialty"), True),
            ("Email", ("email",), False),
        ],
    ),
}


def _rows_for(widget_type: str, data: Dict[str, Any]) -> tuple:
    source_keys, columns = _LIST_SPECS[widget_type]
    items: List[Dict[str, Any]] = []
    for key in source_keys:
        value = data.get(key)
        if isinstance(value, list) and value:
            items = value
            break
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = {header: _first(item, *keys) for header, keys, _ in columns}
        # A row whose every cell is the placeholder asserts a record exists while
        # identifying none of it. A dash in *some* cells is fine — a missing
        # phone number is a fact — but a row of nothing but dashes is noise.
        if any(value != "—" for value in row.values()):
            rows.append(row)
    return rows, columns


def _list_view(widget_type: str, data: Dict[str, Any]) -> DataTable:
    rows, columns = _rows_for(widget_type, data)
    return DataTable(
        columns=[
            DataTableColumn(key=header, header=header, sortable=sortable)
            for header, _, sortable in columns
        ],
        rows=rows,
        # Search earns its space on a long list and clutters a short one.
        search=len(rows) > 8,
        paginated=len(rows) > 25,
    )


def medication_list_view(data: Dict[str, Any]) -> Column:
    """Medications. Mirrors NoEHR's MedicationListWidget row: name, active pill,
    strength/form/route, then directions and the dispense/date metadata."""
    def build(m: Dict[str, Any]) -> List[Any]:
        active = m.get("is_active")
        status = m.get("status") or (
            "Active" if str(active).lower() in ("true", "1", "yes") else
            "Inactive" if active is not None else ""
        )
        meta = _joined(
            {"dates": _date_range(m, ("start_date", "from_date"), ("end_date", "to_date")),
             "dispense": _joined(m, "dispense", "dispense_unit", sep=" ")},
            "dates", "dispense",
        )
        return _record_block(
            _first(m, *_MED_NAME_KEYS, default=""),
            status,
            _joined(m, "strength_description", "doseform_description", "route_description")
            or _first(m, "directions", "sig", default=""),
            _joined({"d": _first(m, "directions", "sig", default=""), "m": meta}, "d", "m"),
        )
    return _records_view(_items(data, "current_medications", "medications"), build,
                         "No medications on the chart.")


def supplement_list_view(data: Dict[str, Any]) -> Column:
    def build(sp: Dict[str, Any]) -> List[Any]:
        return _record_block(
            _first(sp, *_SUPPLEMENT_NAME_KEYS, default=""),
            _status_of(sp, "status", "supplement_status"),
            _joined(sp, "strength", "dosage_form", "route"),
            _joined({"dose": _joined(sp, "dosage", "dosage_unit", sep=" "),
                     "freq": _first(sp, "frequency", "intake_type", default=""),
                     "dates": _date_range(sp, ("start_date",), ("end_date",))},
                    "dose", "freq", "dates"),
        )
    return _records_view(_items(data, "current_supplements", "supplements"), build,
                         "No supplements on the chart.")


def allergy_list_view(data: Dict[str, Any]) -> Column:
    """Allergies. Severity drives the badge, so a severe allergy is visible
    without reading — the one list where colour carries clinical weight."""
    def build(a: Dict[str, Any]) -> List[Any]:
        severity = _first(a, "severity", default="")
        status = _status_of(a, "display_status", "status")
        reactions = a.get("reactions")
        if isinstance(reactions, list):
            reactions = ", ".join(str(r) for r in reactions if r)
        return _record_block(
            _first(a, *_ALLERGEN_KEYS, default=""),
            severity or status,
            f"Reaction: {reactions}" if reactions else "",
            _joined({"type": _first(a, "type", default=""),
                     "observed": _fmt_date(_first(a, "observed_on", default="")),
                     # Severity is the badge, so the status chip only adds
                     # something when it is not already what the badge says.
                     "status": status if status.lower() != severity.lower() else ""},
                    "type", "observed", "status"),
        )
    return _records_view(_items(data, "allergies", "patient_allergies"), build,
                         "No known allergies recorded.")


def diagnosis_list_view(data: Dict[str, Any]) -> Column:
    def build(d: Dict[str, Any]) -> List[Any]:
        code = _joined(d, "code", "code_type", sep=" ")
        return _record_block(
            _first(d, *_DIAGNOSIS_NAME_KEYS, default=""),
            _status_of(d, "status"),
            code,
            _joined({"onset": _date_range(d, ("from_date", "onset_date", "date"), ("to_date",)),
                     "comments": _first(d, "comments", default="")},
                    "onset", "comments"),
        )
    return _records_view(_items(data, "diagnoses", "patient_diagnoses"), build,
                         "No diagnoses on the problem list.")


def vitals_list_view(data: Dict[str, Any]) -> Column:
    """Vitals entries. Each entry holds its own readings list, so a flat lookup
    finds nothing — the same shape that broke the patient summary card."""
    def build(entry: Dict[str, Any]) -> List[Any]:
        readings = [
            f"{r.get('vital_name')}: {str(r.get('vital_value', '')).strip()} "
            f"{str(r.get('vital_unit', '')).strip()}".strip()
            for r in entry.get("vitals") or entry.get("vital_readings") or []
            if isinstance(r, dict) and r.get("vital_name")
        ]
        if not readings:
            return []
        return _record_block(
            _fmt_date(_first(entry, "entry_date", "date", "recorded_date")),
            "",
            " · ".join(readings),
            f"Encounter {entry['encounter_id']}" if entry.get("encounter_id") else "",
        )
    return _records_view(_items(data, "vital_entries", "recent_vitals", "vitals"), build,
                         "No vitals recorded.")


def lab_list_view(data: Dict[str, Any]) -> Column:
    def build(lab: Dict[str, Any]) -> List[Any]:
        tests = lab.get("test_names")
        if isinstance(tests, list):
            tests = ", ".join(str(t) for t in tests if t)
        return _record_block(
            tests or _first(lab, "test_name", "lab_name", "name"),
            _first(lab, "result_status", "status", default=""),
            _first(lab, "interpretation", "result", "result_value", default=""),
            _joined({"reported": _fmt_date(_first(lab, "reported_date", "result_date",
                                                   "collected_date", "order_date", "date",
                                                   default="")),
                     "lab": _first(lab, "lab_name", default=""),
                     "notes": _first(lab, "internal_comments", default="")},
                    "reported", "lab", "notes"),
        )
    return _records_view(_items(data, "lab_results", "lab_orders"), build,
                         "No lab results available.")


def task_list_view(data: Dict[str, Any]) -> Column:
    def build(t: Dict[str, Any]) -> List[Any]:
        owner = t.get("owner")
        owner_name = owner.get("full_name") if isinstance(owner, dict) else _first(t, "owner_name", default="")
        patient = t.get("patient")
        patient_name = patient.get("full_name") if isinstance(patient, dict) else _first(t, "patient_name", default="")
        priority = _task_priority(_first(t, "priority", default=""))
        return _record_block(
            _first(t, "task", "task_name", "name"),
            _first(t, "status", "task_status", default=""),
            _first(t, "comments", default=""),
            _joined({"due": f"Due {_fmt_date(t['due_date'])}" if t.get("due_date") else "",
                     "priority": f"{priority} priority" if priority else "",
                     "owner": owner_name, "patient": patient_name},
                    "due", "priority", "owner", "patient"),
        )
    return _records_view(_items(data, "tasks"), build, "No tasks.")


def recall_list_view(data: Dict[str, Any]) -> Column:
    def build(r: Dict[str, Any]) -> List[Any]:
        return _record_block(
            _first(r, "recall_name", "name", "reason"),
            _status_of(r, "status"),
            _first(r, "notes", "comments", default=""),
            _joined({"due": f"Due {_fmt_date(_first(r, 'due_date', 'recall_date', 'date', default=''))}"
                            if _first(r, "due_date", "recall_date", "date", default="") else "",
                     "provider": _first(r, "provider_name", "member_name", default="")},
                    "due", "provider"),
        )
    return _records_view(_items(data, "recalls", "recall"), build, "No recalls scheduled.")


def note_list_view(data: Dict[str, Any]) -> Column:
    def build(n: Dict[str, Any]) -> List[Any]:
        # The note itself leads. NoEHR's NoteListWidget reads
        # `notes` ?? `content` ?? `text` and puts the date underneath — the wire
        # field is `notes`, plural, which is what this used to miss entirely.
        return _record_block(
            _first(n, "notes", "content", "text", "note", "description", default=""),
            "",
            "",
            _joined({"when": _fmt_date(_first(n, "created_date", "date", "entry_date",
                                              "last_modified_time", default="")),
                     "who": _first(n, "member_name", "provider_name", "created_by",
                                   default="")},
                    "when", "who"),
        )
    return _records_view(_items(data, "quick_notes", "notes"), build, "No notes.")


def encounter_list_view(data: Dict[str, Any]) -> Column:
    def build(e: Dict[str, Any]) -> List[Any]:
        approved = str(e.get("is_approved", "")).lower()
        status = "Signed" if approved in ("true", "1", "yes") else (
            "Unsigned" if approved in ("false", "0", "no") else _first(e, "status", default=""))
        return _record_block(
            _first(e, "visit_name", "encounter_type", "chart_type", default="Encounter"),
            status,
            _first(e, "chief_complaints", "chief_complaint", default=""),
            _joined({"date": _fmt_date(_first(e, "date", "encounter_date", default="")),
                     "provider": _first(e, "provider_name", "physician_name", "member_name", default=""),
                     "facility": _first(e, "facility_name", default="")},
                    "date", "provider", "facility"),
        )
    return _records_view(_items(data, "recent_encounters", "encounters"), build,
                         "No encounters on file.")


def patient_list_view(data: Dict[str, Any]) -> DataTable:
    return _list_view("patient_list", data)


def facility_list_view(data: Dict[str, Any]) -> DataTable:
    return _list_view("facility_list", data)


def provider_list_view(data: Dict[str, Any]) -> DataTable:
    return _list_view("provider_list", data)


# ── Details ───────────────────────────────────────────────────────────


def _detail_card(title: str, metrics: List[tuple], sections: List[tuple]) -> Card:
    """A detail card: a row of identifying metrics, then titled sections.

    `metrics` is (label, value) pairs; `sections` is (title, [lines]).
    """
    body: List[Any] = []
    present = [(label, value) for label, value in metrics if value not in (None, "", "—")]
    if present:
        body.append(Row(gap=6, children=[Metric(label=l, value=v) for l, v in present]))
        body.append(Separator(spacing=2))
    for section_title, lines in sections:
        body += _section(section_title, [line for line in lines if line not in (None, "", "—")])
    if not body:
        body.append(Muted(content="Nothing to show for this record."))
    return Card(
        children=[
            CardHeader(children=[CardTitle(content=title)]),
            CardContent(children=[Column(gap=2, children=body)]),
        ]
    )


def patient_detail_view(data: Dict[str, Any]) -> Card:
    patient = data.get("patient") if isinstance(data.get("patient"), dict) else data
    return _detail_card(
        _first(patient, "patient_name", "full_name", default="Patient"),
        [
            ("MRN", _first(patient, "record_id", "patient_record_id", "mrn")),
            ("DOB", _first(patient, "dob", "date_of_birth")),
            ("Gender", _first(patient, "gender", "sex")),
            ("Phone", _first(patient, "mobile", "home_phone", "phone")),
        ],
        [
            ("Address", [_first(patient, "address_line1", "address"), _first(patient, "city"), _first(patient, "state")]),
            ("Facility", [_first(patient, "facility_name")]),
        ],
    )


def appointment_detail_view(data: Dict[str, Any]) -> Card:
    appt = data.get("appointment") if isinstance(data.get("appointment"), dict) else data
    return _detail_card(
        _first(appt, "patient_name", "full_name", default="Appointment"),
        [
            ("Date", _first(appt, "appointment_date", "date", "start_date")),
            ("Time", _first(appt, "start_time", "appointment_time", "from_time")),
            ("Status", _first(appt, "appointment_status", "status")),
            ("Mode", _first(appt, "mode", "appointment_mode")),
        ],
        [
            ("Reason", [_first(appt, "reason", "appointment_type", "visit_type")]),
            ("Provider", [_first(appt, "provider_name", "member_name", "physician_name")]),
            ("Facility", [_first(appt, "facility_name")]),
        ],
    )


def encounter_detail_view(data: Dict[str, Any]) -> Card:
    details = data.get("encounter_details") or data
    info = details.get("encounter_info") if isinstance(details.get("encounter_info"), dict) else details
    return _detail_card(
        _first(info, "visit_name", "encounter_type", default="Encounter"),
        [
            ("Date", _first(info, "date", "encounter_date")),
            ("Provider", _first(info, "provider_name", "provider", "physician_name")),
            ("Signed", _first(info, "is_approved", "status")),
        ],
        [
            ("Chief complaint", [_first(info, "chief_complaint", "chief_complaints")]),
            ("Assessment", [_first(info, "assessment", "assessment_notes")]),
            ("Plan", [_first(info, "plan", "treatment_plan")]),
        ],
    )


def lab_detail_view(data: Dict[str, Any]) -> Card:
    report = data.get("result_report") if isinstance(data.get("result_report"), dict) else data
    results = report.get("results") or report.get("result_values") or []
    lines = [
        f"{_first(r, 'test_name', 'name')}: {_first(r, 'result', 'value')} "
        f"{_first(r, 'unit', default='')}".strip()
        for r in results
        if isinstance(r, dict)
    ]
    return _detail_card(
        _first(report, "test_name", "lab_name", "panel_name", default="Lab result"),
        [
            ("Collected", _first(report, "collected_date", "order_date", "date")),
            ("Status", _first(report, "status", "result_status")),
            ("Lab", _first(report, "lab_name", "performing_lab")),
        ],
        [("Results", lines)],
    )


def _write_affordances_are_deliberately_absent() -> None:
    """Why no view here has an Add or Save button.

    Three reasons, in order of weight:

    1. **It matches NoEHR.** Its list widgets are read-only —
       `ListWidgetShell` takes no action parameter, and none of the 13 list
       widgets dispatches a `WidgetAction`. Writes live in its detail views,
       behind `.executeWithConfirmation` (a title/message dialog) or
       `.showForm` (a pre-filled sheet), with a per-widget activity log and
       an `isMutating` in-flight guard around them.
    2. **A component that calls a tool is an untested path here.**
       `ToolResult.__init__` runs `_prefab_to_json` without the app name that
       addresses peer-tool references, unlike the bare-component path.
    3. **There is no mutation gate on this route.** Cortex's approval
       pipeline is not on the direct-to-MCP path, so the only thing in front of
       a write is whatever per-tool consent the client offers — which a user
       typically grants once and forgets. A write button turns "the model might
       call a write" into "the UI invites one".

    Adding them is a deliberate decision with a gate question attached, not a
    completeness exercise.
    """


_VIEWS.update({
    "allergy_list": allergy_list_view,
    "appointment_detail": appointment_detail_view,
    "appointment_list": appointment_list_view,
    "diagnosis_list": diagnosis_list_view,
    "encounter_detail": encounter_detail_view,
    "encounter_list": encounter_list_view,
    "facility_list": facility_list_view,
    "lab_detail": lab_detail_view,
    "lab_list": lab_list_view,
    "medication_list": medication_list_view,
    "note_list": note_list_view,
    "patient_detail": patient_detail_view,
    "patient_history": patient_summary_view,
    "patient_list": patient_list_view,
    "provider_list": provider_list_view,
    "recall_list": recall_list_view,
    "supplement_list": supplement_list_view,
    "task_list": task_list_view,
    "vitals_list": vitals_list_view,
})
