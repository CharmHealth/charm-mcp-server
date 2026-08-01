from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_http_headers
from typing import Optional, List, Dict, Any, Literal, Union
from api import CharmHealthAPIClient
from common.utils import strip_empty_values
import json
import logging
from telemetry import telemetry, with_tool_metrics

logger = logging.getLogger(__name__)

intake_forms_mcp = FastMCP(name="CharmHealth Intake Forms MCP Server")


@intake_forms_mcp.tool
@with_tool_metrics()
async def manageIntakeForms(
    action: Literal[
        "list_templates",
        "create_template",
        "get_patient_forms",
        "share_sms",
        "share_portal",
        "get_responses",
        "get_responses_pdf",
    ],
    patient_id: Optional[str] = None,
    questionnaire_id: Optional[str] = None,   # template ID — which form to send/list
    answer_id: Optional[str] = None,          # the ques_map_id from get_patient_forms — a specific patient/form assignment, different from questionnaire_id (the template)
    questionnaire_type: Optional[str] = None, # filter for list_templates; also the type for create_template
    facility_id: Optional[str] = None,        # required for share_sms/share_portal — the real API has no per-patient default
    appointment_id: Optional[str] = None,     # optional filter for get_patient_forms — forms tied to a specific visit

    # create_template fields
    questionnaire_name: Optional[str] = None,     # -> API "name", 3-100 chars
    comments: Optional[str] = None,               # optional for create_template, max 250 chars
    # Accepts a real JSON array OR a JSON-encoded string of one. Models calling this
    # tool sometimes stringify nested arrays (this codebase's own manageMessages uses
    # a comma-separated *string* for recipient_member_ids, which appears to bias some
    # models toward stringifying list-shaped params generally). A plain
    # List[Dict[str, Any]] type gets rejected by FastMCP's own pydantic validation
    # *before* this function body ever runs when a string is sent instead — so the
    # coercion has to happen via a wider accepted type + explicit json.loads below,
    # not a runtime check inside the function.
    questions: Optional[Union[str, List[Dict[str, Any]]]] = None,

    ctx: Context = None,
) -> Dict[str, Any]:
    """
    Manage patient intake forms (questionnaires).

    <usecase>
    Send pre-visit intake/consent forms to patients and retrieve their completed responses.
    Covers the practice's questionnaire templates, sharing a form with a patient via SMS or
    the patient portal, and reading back what a patient submitted.
    </usecase>

    <instructions>
    Actions:
    - "list_templates": List available questionnaire templates (optionally filter by questionnaire_type).
      Use this first to discover a valid questionnaire_id before sharing a form with a patient.
    - "create_template": Create a new questionnaire template (requires questionnaire_name, questionnaire_type,
      questions; comments is optional, max 250 chars).

      questionnaire_type must be one of: "General Questionnaire", "Feedback Form", "Pre-screening Form",
      "Consent Form" — per CharmHealth's createQuestionnaireJSON validation template, these are the four
      creatable types.

      Questions must be passed as a native JSON array value (not a JSON-encoded string —
      e.g. [{"notes_type": "Label", "notes": "..."}], NOT "[{\"notes_type\": ...}]").
      A stringified array will be auto-parsed if valid JSON, but pass a real array directly.
      Each question object requires:
      - notes_type: the question "kind" — legal values depend on questionnaire_type (see table below;
        this is enforced in code, not just documented — an illegal combination is rejected before the
        API call happens).
      - notes: the question text (3-20000 chars).
      Optional per question: is_mandatory (bool, default false; forced false for Label/widget types).

      Legal notes_type values per questionnaire_type:
      - "Feedback Form": Label, Simple Question, Question, Rating, Question with Options, Question with Fixed Options
      - "Pre-screening Form": Label, Simple Question, Question, Question with Options, Question with Fixed Options
      - "Consent Form": Label, Simple Question, Question, Date, Question with Options, Question with Fixed
        Options, Rating Scale, Yes/No Question, Signature
      - "General Questionnaire": Label, Simple Question, Question, Rating Scale, Question with Options,
        Question with Fixed Options, Date, Yes/No Question, Signature, Allergies, Medications, Supplements,
        Personal Details, Primary Contact Details, Primary Insurance Details. Note plain "Rating" (as opposed
        to "Rating Scale") is NOT legal here — use "Feedback Form" if you need a Rating question.

      Conditional fields required per notes_type:
      - "Question with Options" / "Question with Fixed Options": options (required — array of {"option": "..."},
        1-100 items, each ≤250 chars); is_multi_choice (bool, optional — true for checkbox-style, false for radio-style)
      - "Rating Scale": from_scale and to_scale (ints; from_scale <= to_scale; range ≤ 15)
      - "Rating": description (object mapping "1".."5" to a label string, ≤50 chars each)
      - "Allergies": options (OPTIONAL — array of {"option": "..."}, 1-3 items, each value one of
        "Drug Allergy"/"Food Allergy"/"Environmental Allergy" — the real API's fixed allow-list for this widget)
      - "Label": label_style (object, OPTIONAL — omit it entirely for a plain default look: font_weight="normal",
        text_decoration="none", font_size=14, font_style="normal", text_align="left". The real API requires this
        field, but this tool fills in sensible defaults so you don't have to specify it). If you do pass it,
        any subset of keys is fine — unspecified keys still get defaulted. Keys: font_weight ("bold"|"normal"),
        text_decoration ("underline"|"none"), font_size (a JSON number 11-20, NOT a quoted string — e.g. 16, not
        "16"), font_style ("italic"|"normal"), text_align ("left"|"right"|"center"|"justify"). A wrong type on a
        key you do supply (e.g. font_size as a string) is not rejected cleanly by the real API — it comes back
        as an opaque HTTP 500 "Internal Error" instead of a 400.

      Worked example (General Questionnaire, no label_style needed):
        questions=[
          {"notes_type": "Label", "notes": "Medical History"},
          {"notes_type": "Allergies", "notes": "Please list any known allergies."},
          {"notes_type": "Rating Scale", "notes": "Rate your pain level", "from_scale": 1, "to_scale": 5},
          {"notes_type": "Question with Options", "notes": "Preferred contact method?",
           "options": [{"option": "Phone"}, {"option": "Email"}], "is_multi_choice": false}
        ]
      All numeric fields (font_size, from_scale, to_scale) must be real JSON numbers, not quoted strings.

      Do not pass entry_id or is_deleted on create — those only apply to action="update" (not yet
      implemented in this tool).
    - "get_patient_forms": List questionnaires assigned to or filled by a specific patient (requires patient_id).
      Pass the optional appointment_id to filter down to forms tied to that specific visit (e.g. to check
      whether a patient still has an outstanding form before that appointment). Omit appointment_id to see
      all forms for the patient regardless of visit. Each returned item's ques_map_id is what
      get_responses/get_responses_pdf expect as answer_id.
    - "share_sms": Text a form link to the patient (requires patient_id, facility_id, questionnaire_id).
      facility_id is required by the real API — there is no per-patient default. NOT appointment-scoped —
      this sends the form to the patient generally, not tied to any specific visit. There is no phone-number
      override; the API always uses the patient's stored contact number.
    - "share_portal": Push a form into the patient's portal (PHR) to fill out (requires patient_id, facility_id,
      questionnaire_id). Same as share_sms: NOT appointment-scoped.
    - "get_responses": Fetch a patient's submitted answers for a specific form (requires answer_id,
      NOT questionnaire_id — use get_patient_forms first to find the ques_map_id for a completed submission,
      and pass that value as answer_id).
    - "get_responses_pdf": Download a completed form as a PDF (requires answer_id, same as get_responses).

    IMPORTANT — questionnaire_id vs answer_id: questionnaire_id identifies a *template* (the blank form).
    answer_id is actually the ques_map_id of one specific patient/form assignment (what get_patient_forms
    returns) — do not confuse the two. get_responses and get_responses_pdf need answer_id, not questionnaire_id.

    When required parameters are missing, ask the user to provide the specific values rather than
    proceeding with defaults or auto-generated values.
    </instructions>
    """
    access_token = None
    refresh_token = None
    base_url = None
    token_url = None
    client_secret = None
    accounts_server = None

    try:
        headers = get_http_headers()
        access_token = headers.get('x-user-access-token')
        refresh_token = headers.get('x-user-refresh-token')
        base_url = headers.get('x-charmhealth-base-url')
        token_url = headers.get('x-charmhealth-token-url')
        client_secret = headers.get('x-charmhealth-client-secret')
        accounts_server = headers.get('x-charmhealth-accounts-server')

        if accounts_server:
            token_url = f"{accounts_server.rstrip('/')}/oauth/v2/token"

        if base_url and not base_url.endswith('/api/ehr/v1'):
            base_url = base_url.rstrip('/') + '/api/ehr/v1'

        if access_token:
            logger.info("manageIntakeForms using user credentials")
        else:
            logger.info("manageIntakeForms using environment variable credentials")
    except Exception as e:
        logger.debug(f"Could not get HTTP headers (might be stdio mode): {e}")

    async with CharmHealthAPIClient(
        access_token=access_token,
        refresh_token=refresh_token,
        base_url=base_url,
        token_url=token_url,
        client_secret=client_secret
    ) as client:
        try:
            match action:
                case "list_templates":
                    params: Dict[str, Any] = {}
                    if questionnaire_type:
                        params["type"] = questionnaire_type

                    response = await client.get("/questionnaires", params=params)
                    templates = response.get("questionnaires") or []
                    response["total_count"] = len(templates)
                    if templates:
                        response["guidance"] = (
                            f"Found {len(templates)} questionnaire template(s). Use action='share_sms' "
                            "or action='share_portal' with a questionnaire_id and patient_id to send one."
                        )
                    elif response.get("error"):
                        response["guidance"] = "Failed to list questionnaire templates. Verify questionnaire_type is a legal value."
                    else:
                        response["guidance"] = "No questionnaire templates found matching the filter."
                    return strip_empty_values(response)

                case "create_template":
                    # Coerce a stringified JSON array back into a real list. Some
                    # callers send questions as a JSON-encoded string instead of a
                    # native array — accept it rather than fail with an opaque
                    # protocol-level schema error the caller can't act on.
                    if isinstance(questions, str):
                        try:
                            questions = json.loads(questions)
                        except json.JSONDecodeError:
                            return {
                                "error": "questions must be a JSON array of question objects, not a plain string",
                                "guidance": "Pass questions as an actual array value, e.g. "
                                            '[{"notes_type": "Label", "notes": "..."}], not a JSON-encoded string.'
                            }
                        if not isinstance(questions, list):
                            return {
                                "error": "questions must be a JSON array of question objects",
                                "guidance": "The decoded value wasn't a list. Pass questions as an array of "
                                            "question objects, e.g. [{\"notes_type\": \"Label\", \"notes\": \"...\"}]."
                            }

                    if not questionnaire_name or not questionnaire_type or not questions:
                        return {
                            "error": "questionnaire_name, questionnaire_type, and questions required for create_template",
                            "guidance": "Provide a name (3-100 chars), a type (General Questionnaire, Feedback Form, "
                                        "Pre-screening Form, or Consent Form), and at least one question. "
                                        "comments is optional (max 250 chars)."
                        }

                    # Length/count bounds from CharmHealth's Questionnaire Settings API reference.
                    top_level_errors: List[str] = []
                    if not isinstance(questionnaire_name, str) or not (3 <= len(questionnaire_name) <= 100):
                        top_level_errors.append(
                            f"questionnaire_name must be a string 3-100 chars (got {len(questionnaire_name) if isinstance(questionnaire_name, str) else questionnaire_name!r})"
                        )
                    # comments has no min-occurrences in createQuestionnaireJSON (unlike
                    # name/type/questions, which all say min-occurrences="1") — it's optional.
                    # Only validate it if the caller actually supplied one.
                    if comments is not None and (not isinstance(comments, str) or len(comments) > 250):
                        top_level_errors.append(
                            f"comments must be a string of at most 250 chars (got {len(comments) if isinstance(comments, str) else comments!r})"
                        )
                    if not isinstance(questions, list) or not (1 <= len(questions) <= 200):
                        top_level_errors.append(
                            f"questions must be a non-empty array of at most 200 items (got {len(questions) if isinstance(questions, list) else questions!r})"
                        )
                    if top_level_errors:
                        return {
                            "error": "Invalid questionnaire_name/comments/questions for create_template",
                            "guidance": " | ".join(top_level_errors)
                        }

                    # Per createQuestionnaireJSON's own validation template (type
                    # regex="General Questionnaire|Feedback Form|Pre-screening Form|Consent Form"),
                    # these four are the documented creatable types.
                    creatable_types = {"General Questionnaire", "Feedback Form", "Pre-screening Form", "Consent Form"}
                    if questionnaire_type not in creatable_types:
                        return {
                            "error": f"Invalid questionnaire_type for create_template: {questionnaire_type}",
                            "guidance": "questionnaire_type must be one of: General Questionnaire, Feedback Form, "
                                        "Pre-screening Form, Consent Form. 'New Patient Form' is a fixed, "
                                        "practice-level type "
                        }

                    # Pre-flight notes_type legality check, enforced for all four creatable
                    # types (per CharmHealth's Questionnaire Settings API reference — Table 5).
                    # Catching this here turns an opaque HTTP 400 into actionable guidance
                    # naming the exact offending question and the real legal set.
                    legal_notes_types_by_questionnaire_type: Dict[str, set] = {
                        "Feedback Form": {
                            "Label", "Simple Question", "Question", "Rating",
                            "Question with Options", "Question with Fixed Options",
                        },
                        "Pre-screening Form": {
                            "Label", "Simple Question", "Question",
                            "Question with Options", "Question with Fixed Options",
                        },
                        "Consent Form": {
                            "Label", "Simple Question", "Question", "Date",
                            "Question with Options", "Question with Fixed Options",
                            "Rating Scale", "Yes/No Question", "Signature",
                        },
                        "General Questionnaire": {
                            "Label", "Simple Question", "Question", "Rating Scale",
                            "Question with Options", "Question with Fixed Options", "Date",
                            "Yes/No Question", "Signature", "Allergies", "Medications", "Supplements",
                            "Personal Details", "Primary Contact Details", "Primary Insurance Details",
                        },
                    }
                    legal_set = legal_notes_types_by_questionnaire_type[questionnaire_type]
                    bad_questions = [
                        (i, q.get("notes_type")) for i, q in enumerate(questions)
                        if isinstance(q, dict) and q.get("notes_type") not in legal_set
                    ]
                    if bad_questions:
                        offenders = ", ".join(f"questions[{i}].notes_type={nt!r}" for i, nt in bad_questions)
                        return {
                            "error": f"notes_type not legal for questionnaire_type '{questionnaire_type}': {offenders}",
                            "guidance": f"Legal notes_type values for '{questionnaire_type}' are: "
                                        f"{sorted(legal_set)}. Adjust or remove the flagged question(s), "
                                        "or use a different questionnaire_type if a broader set of question "
                                        "kinds is needed."
                        }

                    # Pre-flight conditional-field check. notes_type legality alone isn't
                    # enough — several notes_types require extra fields the real API
                    # enforces server-side (e.g. "Please provide label style for ..." is
                    # exactly what a missing label_style on a Label question produces).
                    # Catch these here with a specific per-question error instead of
                    # letting the real API 400 be the first signal.
                    _LABEL_STYLE_DEFAULTS = {
                        "font_weight": "normal",
                        "text_decoration": "none",
                        "font_size": 14,
                        "font_style": "normal",
                        "text_align": "left",
                    }
                    _WIDGET_TYPES = {
                        "Allergies", "Medications", "Supplements", "Personal Details",
                        "Primary Contact Details", "Primary Insurance Details",
                    }
                    _ALLERGY_OPTIONS = {"Drug Allergy", "Food Allergy", "Environmental Allergy"}
                    conditional_errors: List[str] = []
                    widget_type_counts: Dict[str, int] = {}
                    for i, q in enumerate(questions):
                        if not isinstance(q, dict):
                            conditional_errors.append(f"questions[{i}] must be an object, not {type(q).__name__}")
                            continue
                        nt = q.get("notes_type")

                        # Generic per-question checks — apply regardless of notes_type, since
                        # these two fields are documented as required/typed for every question,
                        # not just conditionally for specific notes_types.
                        notes = q.get("notes")
                        if not isinstance(notes, str) or not (3 <= len(notes) <= 20000):
                            conditional_errors.append(
                                f"questions[{i}] is missing a valid 'notes' field (required string, 3-20000 chars)"
                            )

                        is_mandatory = q.get("is_mandatory")
                        if isinstance(is_mandatory, str) and is_mandatory.strip().lower() in ("true", "false"):
                            is_mandatory = is_mandatory.strip().lower() == "true"
                            q["is_mandatory"] = is_mandatory
                        if is_mandatory is not None and not isinstance(is_mandatory, bool):
                            conditional_errors.append(
                                f"questions[{i}].is_mandatory must be a boolean, not {is_mandatory!r}"
                            )

                        # is_multi_choice has no notes_type restriction at the schema level either
                        # (only meaningful for Question with Options/Question with Fixed Options by
                        # convention) — validate it universally, same as is_mandatory, rather than
                        # only inside that one branch.
                        is_multi_choice = q.get("is_multi_choice")
                        if isinstance(is_multi_choice, str) and is_multi_choice.strip().lower() in ("true", "false"):
                            is_multi_choice = is_multi_choice.strip().lower() == "true"
                            q["is_multi_choice"] = is_multi_choice
                        if is_multi_choice is not None and not isinstance(is_multi_choice, bool):
                            conditional_errors.append(
                                f"questions[{i}].is_multi_choice must be a boolean, not {is_multi_choice!r}"
                            )

                        if nt == "Label" or nt in _WIDGET_TYPES:
                            # Matches the real API's own behavior (forced false
                            # server-side for Label/widget types) — enforcing it
                            # here too keeps the request we send honest about
                            # what will actually get stored, instead of sending
                            # `true` for something the backend silently drops.
                            q["is_mandatory"] = False

                        if nt == "Label":
                            # The real API requires label_style server-side, but callers
                            # shouldn't have to specify all five sub-fields just to add a
                            # section header — default whatever's missing to a plain,
                            # unstyled look and only validate the fields that were actually
                            # supplied. Caller can still override any subset (e.g. just
                            # font_weight="bold") without having to spell out the rest.
                            label_style = q.get("label_style")
                            if not isinstance(label_style, dict):
                                label_style = {}
                            for key, default in _LABEL_STYLE_DEFAULTS.items():
                                label_style.setdefault(key, default)
                            q["label_style"] = label_style

                            # Key presence alone isn't enough — a right-shaped-but-wrong-typed
                            # value (e.g. font_size sent as "16" instead of 16, the same
                            # stringification habit models show with array params elsewhere
                            # in this tool) isn't rejected cleanly by the real API. It comes
                            # back as an opaque HTTP 500 "Internal Error", not a 400, so this
                            # was invisible until bisected down to a single field. Coerce an
                            # obviously-numeric string rather than just rejecting it, then
                            # validate the actual value/range/enum for every label_style field.
                            font_size = label_style.get("font_size")
                            if isinstance(font_size, str) and font_size.strip().lstrip("-").isdigit():
                                font_size = int(font_size.strip())
                                label_style["font_size"] = font_size

                            label_style_errors = []
                            if not isinstance(font_size, int) or isinstance(font_size, bool) or not (11 <= font_size <= 20):
                                label_style_errors.append(
                                    f"font_size must be a JSON number 11-20, not {label_style.get('font_size')!r}"
                                )
                            if label_style.get("font_weight") not in ("bold", "normal"):
                                label_style_errors.append(
                                    f"font_weight must be 'bold' or 'normal', not {label_style.get('font_weight')!r}"
                                )
                            if label_style.get("text_decoration") not in ("underline", "none"):
                                label_style_errors.append(
                                    f"text_decoration must be 'underline' or 'none', not {label_style.get('text_decoration')!r}"
                                )
                            if label_style.get("font_style") not in ("italic", "normal"):
                                label_style_errors.append(
                                    f"font_style must be 'italic' or 'normal', not {label_style.get('font_style')!r}"
                                )
                            if label_style.get("text_align") not in ("left", "right", "center", "justify"):
                                label_style_errors.append(
                                    f"text_align must be one of left/right/center/justify, not {label_style.get('text_align')!r}"
                                )

                            if label_style_errors:
                                conditional_errors.append(
                                    f"questions[{i}] (notes_type='Label') has an invalid label_style: "
                                    + "; ".join(label_style_errors)
                                )
                        elif nt in ("Question with Options", "Question with Fixed Options"):
                            options = q.get("options")
                            if not options or not isinstance(options, list):
                                conditional_errors.append(
                                    f"questions[{i}] (notes_type={nt!r}) is missing options (non-empty array required)"
                                )
                            else:
                                if not (1 <= len(options) <= 100):
                                    conditional_errors.append(
                                        f"questions[{i}] (notes_type={nt!r}) options must have 1-100 items (got {len(options)})"
                                    )
                                bad_options = [
                                    idx for idx, opt in enumerate(options)
                                    if not (isinstance(opt, dict) and isinstance(opt.get("option"), str)
                                            and 0 < len(opt.get("option")) <= 250)
                                ]
                                if bad_options:
                                    conditional_errors.append(
                                        f"questions[{i}] (notes_type={nt!r}) options{bad_options} must each be an "
                                        'object shaped {"option": "..."} with a non-empty string of at most 250 chars'
                                    )
                        elif nt == "Allergies" and q.get("options") is not None:
                            # options is optional here (unlike Question with Options, where it's
                            # required) — the real API has a fixed 3-item allow-list for this
                            # widget, so only validate it if the caller actually supplied one.
                            options = q.get("options")
                            if not isinstance(options, list):
                                conditional_errors.append(
                                    f"questions[{i}] (notes_type='Allergies') options must be an array"
                                )
                            else:
                                if not (1 <= len(options) <= 3):
                                    conditional_errors.append(
                                        f"questions[{i}] (notes_type='Allergies') options must have 1-3 items (got {len(options)})"
                                    )
                                bad_options = [
                                    idx for idx, opt in enumerate(options)
                                    if not (isinstance(opt, dict) and opt.get("option") in _ALLERGY_OPTIONS)
                                ]
                                if bad_options:
                                    conditional_errors.append(
                                        f"questions[{i}] (notes_type='Allergies') options{bad_options} must each be "
                                        f'{{"option": "..."}} with option one of {sorted(_ALLERGY_OPTIONS)}'
                                    )
                        elif nt == "Rating Scale":
                            fs, ts = q.get("from_scale"), q.get("to_scale")
                            # Same stringification habit as font_size — coerce an obviously
                            # numeric string rather than rejecting it outright, so a model
                            # that sends "1"/"5" instead of 1/5 still succeeds first try.
                            if isinstance(fs, str) and fs.strip().lstrip("-").isdigit():
                                fs = int(fs.strip())
                                q["from_scale"] = fs
                            if isinstance(ts, str) and ts.strip().lstrip("-").isdigit():
                                ts = int(ts.strip())
                                q["to_scale"] = ts

                            if fs is None or ts is None:
                                conditional_errors.append(
                                    f"questions[{i}] (notes_type='Rating Scale') is missing from_scale/to_scale"
                                )
                            elif not isinstance(fs, int) or isinstance(fs, bool) or not isinstance(ts, int) or isinstance(ts, bool) \
                                    or fs > ts or (ts - fs) > 15:
                                conditional_errors.append(
                                    f"questions[{i}] (notes_type='Rating Scale') has invalid from_scale/to_scale "
                                    f"({fs!r}, {ts!r}) — need integers with from_scale <= to_scale and a range of at most 15"
                                )
                            elif not (0 <= fs <= 9999) or not (0 <= ts <= 9999):
                                # questions_list's schema caps from_scale/to_scale at max-len="4"
                                # (at most 4 digits) — a range-valid pair like (10000, 10010)
                                # would otherwise slip past the range check above.
                                conditional_errors.append(
                                    f"questions[{i}] (notes_type='Rating Scale') from_scale/to_scale "
                                    f"({fs!r}, {ts!r}) must each be at most 4 digits (0-9999)"
                                )
                        elif nt == "Rating":
                            description = q.get("description")
                            if not (isinstance(description, dict) and {"1", "2", "3", "4", "5"} <= description.keys()):
                                conditional_errors.append(
                                    f"questions[{i}] (notes_type='Rating') is missing description "
                                    '(object with all of keys "1"-"5", each a label string, max 50 chars)'
                                )
                            else:
                                bad_labels = [
                                    k for k in ("1", "2", "3", "4", "5")
                                    if not isinstance(description.get(k), str) or not (0 < len(description.get(k)) <= 50)
                                ]
                                if bad_labels:
                                    conditional_errors.append(
                                        f"questions[{i}] (notes_type='Rating') description label(s) {bad_labels} "
                                        "must each be a non-empty string of at most 50 chars"
                                    )

                        if nt in _WIDGET_TYPES:
                            widget_type_counts[nt] = widget_type_counts.get(nt, 0) + 1

                    duplicate_widgets = [nt for nt, count in widget_type_counts.items() if count > 1]
                    if duplicate_widgets:
                        conditional_errors.append(
                            f"widget type(s) used more than once: {duplicate_widgets} "
                            "(each widget type may appear at most once per questionnaire)"
                        )

                    if conditional_errors:
                        return {
                            "error": "Missing or invalid conditional fields in questions",
                            "guidance": " | ".join(conditional_errors)
                        }

                    template_data: Dict[str, Any] = {
                        "name": questionnaire_name,
                        "type": questionnaire_type,
                        "questions": questions,
                    }
                    if comments is not None:
                        template_data["comments"] = comments

                    response = await client.post("/questionnaire", data=template_data)
                    if response.get("error"):
                        response["guidance"] = (
                            "Failed to create the questionnaire template. Common causes: a notes_type not legal "
                            "for this questionnaire_type, a missing conditional field (options/from_scale-to_scale/"
                            "description/label_style) for that notes_type, or a widget type used more than once."
                        )
                    else:
                        response["guidance"] = (
                            "Questionnaire template created. Use action='list_templates' to confirm it and find "
                            "its questionnaire_id, then 'share_sms'/'share_portal' to send it to a patient."
                        )
                    return strip_empty_values(response)

                case "get_patient_forms":
                    if not patient_id:
                        return {
                            "error": "patient_id required for get_patient_forms",
                            "guidance": "Provide the patient_id to check which forms are assigned to or filled by this patient."
                        }

                    params: Dict[str, Any] = {}
                    if appointment_id:
                        params["appointment_id"] = appointment_id

                    response = await client.get(f"/patients/{patient_id}/questionnaires", params=params)
                    # Confirmed against EntityXMLFormat.xml: this endpoint wraps under
                    # "patient_questionnaires" (fields: ques_map_id, questionnaire_id,
                    # questionnaire_name, appointment_id, is_saved, is_submitted), not
                    # "questionnaires" — that key belongs to /questionnaires (list_templates),
                    # a different endpoint. Previously always returned 0 forms.
                    forms = response.get("patient_questionnaires") or []
                    response["total_count"] = len(forms)
                    if forms:
                        if appointment_id:
                            response["guidance"] = (
                                f"Found {len(forms)} form(s) tied to appointment {appointment_id}. Use action='get_responses' "
                                "with the relevant answer_id to read a completed submission."
                            )
                        else:
                            response["guidance"] = (
                                f"Found {len(forms)} form(s) for this patient. Use action='get_responses' with the "
                                "relevant answer_id to read a completed submission."
                            )
                    elif response.get("error"):
                        response["guidance"] = "Failed to retrieve forms for this patient. Verify patient_id is correct."
                    else:
                        if appointment_id:
                            response["guidance"] = (
                                f"No forms found tied to appointment {appointment_id}. To attach one, use "
                                "manageAppointments(action='schedule' or 'reschedule', questionnaire=[{'questionnaire_id': ...}]) "
                                "— manageIntakeForms doesn't assign forms to appointments directly."
                            )
                        else:
                            response["guidance"] = (
                                "No forms found for this patient yet. Use action='share_sms' or 'share_portal' to send one "
                                "generally, or manageAppointments to tie one to a specific visit."
                            )
                    return strip_empty_values(response)

                case "share_sms":
                    if not patient_id or not facility_id or not questionnaire_id:
                        return {
                            "error": "patient_id, facility_id, and questionnaire_id required for share_sms",
                            "guidance": "Provide patient_id, facility_id, and questionnaire_id (use "
                                        "action='list_templates' to find a valid questionnaire_id)."
                        }

                    try:
                        patient_id_int = int(patient_id)
                        facility_id_int = int(facility_id)
                        questionnaire_id_int = int(questionnaire_id)
                    except (ValueError, TypeError):
                        return {
                            "error": "patient_id, facility_id, and questionnaire_id must be numeric",
                            "guidance": "All three should be the numeric IDs returned by findPatients / "
                                        "getPracticeInfo / action='list_templates', not names or other text.",
                        }

                    # Confirmed against QuestionnaireAPIHandler.shareQuestionnairesByLink: facility_id
                    # is required (the call throws immediately without it), and the template ID goes
                    # in a "questionnaires" array of {"questionnaire_id": ...} objects, not a flat
                    # "questionnaire_id" field. There is no phone-number override field at all — the
                    # real API always looks up the patient's stored contact number itself.
                    share_data: Dict[str, Any] = {
                        "patient_id": patient_id_int,
                        "facility_id": facility_id_int,
                        "questionnaires": [{"questionnaire_id": questionnaire_id_int}],
                    }

                    response = await client.post("/questionnaires/share/sms", data=share_data)
                    if response.get("error"):
                        response["guidance"] = "Failed to text the form. Verify patient_id and questionnaire_id are correct and the patient has a valid phone number on file."
                    else:
                        response["guidance"] = "Form texted to the patient. Use action='get_patient_forms' later to check whether it's been completed."
                    return strip_empty_values(response)

                case "share_portal":
                    if not patient_id or not facility_id or not questionnaire_id:
                        return {
                            "error": "patient_id, facility_id, and questionnaire_id required for share_portal",
                            "guidance": "Provide patient_id, facility_id, and questionnaire_id (use "
                                        "action='list_templates' to find a valid questionnaire_id)."
                        }

                    try:
                        patient_id_int = int(patient_id)
                        facility_id_int = int(facility_id)
                        questionnaire_id_int = int(questionnaire_id)
                    except (ValueError, TypeError):
                        return {
                            "error": "patient_id, facility_id, and questionnaire_id must be numeric",
                            "guidance": "All three should be the numeric IDs returned by findPatients / "
                                        "getPracticeInfo / action='list_templates', not names or other text.",
                        }

                    # Same real shape as share_sms, confirmed against
                    # QuestionnaireAPIHandler.shareQuestionnairesToPHR.
                    share_data = {
                        "patient_id": patient_id_int,
                        "facility_id": facility_id_int,
                        "questionnaires": [{"questionnaire_id": questionnaire_id_int}],
                    }

                    response = await client.post("/questionnaires/share/phr", data=share_data)
                    if response.get("error"):
                        response["guidance"] = "Failed to push the form to the patient portal. Verify patient_id and questionnaire_id are correct and the patient has portal access."
                    else:
                        response["guidance"] = "Form pushed to the patient's portal. Use action='get_patient_forms' later to check whether it's been completed."
                    return strip_empty_values(response)

                case "get_responses":
                    if not answer_id:
                        return {
                            "error": "answer_id required for get_responses",
                            "guidance": "Provide the answer_id for a completed submission — use action='get_patient_forms' first to find it. Note: answer_id is not the same as questionnaire_id."
                        }

                    response = await client.get(f"/questionnaire/answer/{answer_id}")
                    if response.get("error"):
                        response["guidance"] = "Could not find responses for that answer_id. Verify the ID with action='get_patient_forms'."
                    else:
                        response["guidance"] = "Responses retrieved. Review before documenting findings in the encounter."
                    return strip_empty_values(response)

                case "get_responses_pdf":
                    if not answer_id:
                        return {
                            "error": "answer_id required for get_responses_pdf",
                            "guidance": "Provide the answer_id for a completed submission — use action='get_patient_forms' first to find it."
                        }

                    response = await client.get(f"/questionnaire/answer/{answer_id}/pdf")
                    if response.get("error"):
                        response["guidance"] = "Could not download the PDF for that answer_id. Verify the ID with action='get_patient_forms'."
                    else:
                        response["guidance"] = "PDF retrieved."
                    return strip_empty_values(response)

        except Exception as e:
            logger.error(f"Error in manageIntakeForms: {e}")
            return {
                "error": str(e),
                "guidance": f"Failed to {action}. Verify patient_id/questionnaire_id/answer_id are correct and you have appropriate permissions."
            }
