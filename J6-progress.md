# CH-688 (J6) — Progress Notes

Started as scratch notes while building `manageIntakeForms` and `managePatientBilling`; kept
(renamed from `CH-688-notes.md`) as a running progress/backtrack log instead of being deleted.
Most of the discoveries below have since been folded into `CLAUDE.md`'s Known Pitfalls — see
the mapping at the bottom for where each one landed.

---

## Status (as of 2026-07-27)

- **Code:** `manageIntakeForms` (`list_templates`, `create_template`, `get_patient_forms`,
  `share_sms`, `share_portal`, `get_responses`, `get_responses_pdf`) and `managePatientBilling`
  (`get_balance`, `list_invoices`, `get_receipts`, `send_balance_reminder`) implemented and
  mounted in `mcp_server.py`. `record_payment` deliberately excluded (see below).
- **Branch:** `ch688-mcp-wave1-tools-actions`, 1 commit ahead of `main`, pushed and in sync with
  `origin`.
- **cortex side:** gating for `send_balance_reminder`/`share_sms`/`share_portal`/`create_template`
  landed on `charm-cortex`'s `CH688-mcp-wave-tools-billing-intakeforms` branch (4 commits ahead of
  `main`, pushed). `test_mutation_catalog.py` + `test_mutation_policy.py` — 48 passed.
- **Still open:**
  - No PR opened yet on either repo; neither branch is merged into `main`.
  - No test files exist for `intake_forms.py`/`billing.py` on the mcp-server side.
  - eRx enrollment/EPCS subtask (separate tool, `manageErxEnrollment`) is blocked on a missing
    API (L8) — out of scope for this pass, tracked as the one unchecked box on CH-688.

---

## Questionnaire API (for `manageIntakeForms`) — discovered endpoints

### 1. Templates (practice-level setup — likely NOT this tool's scope)

| Method | Path | Purpose |
|---|---|---|
| GET | `/questionnaires` | list all templates (filterable by type) |
| POST | `/questionnaire` | create new template |
| GET | `/questionnaire/{id}` | fetch template detail |
| PUT | `/questionnaire/{id}` | edit template |
| DELETE | `/questionnaire/{id}` | delete template |
| GET | `/questionnaire/preferences` | per-facility/type config |

### 2. Patient submissions/responses

| Method | Path | Purpose |
|---|---|---|
| POST | `/questionnaire/answers` | save a patient's filled-in answers (also handles new-patient intake data — contacts, insurance, allergy/med widgets) |
| GET | `/questionnaire/answer/{id}` | fetch a patient's submitted answers |
| GET | `/questionnaire/answer/{id}/pdf` | download filled form as PDF |
| GET | `/patients/{id}/questionnaires` | list questionnaires assigned to/filled by a patient |
| GET | `/answers/{id}/download` | download a signature image on an answer |

### 3. Signatures
`GET/POST/DELETE /questionnaire/signature/{id}/{id}` — fetch/save/delete a signature tied to a form entry.

### 4. Sharing/distribution (the actual intake workflow)
- `POST /questionnaires/share/sms` — text a form link to a patient
- `POST /questionnaires/share/phr` — push a form into the patient portal (PHR) to fill out
- Legacy: `/api/ehr/facilities/patients/shared-questionnaires` (`SharedQuestionnairesController.java`)
- Automation: `SEND_QUESTIONNAIRE` workflow action (auto-send pre-visit intake on a schedule) in `security-api-settings.xml`

### 5. Flowsheet integration
`GET /settings/flowsheet/questionnaire[/{id}]` — attach/read questionnaires inside the vitals/flowsheet workflow.

### 6. FHIR v2
`/fhir/QuestionnaireResponse[/{id}][/_search][/pdf]` — standard FHIR-exposed questionnaire responses.

---

## Design decision: revised action set for `manageIntakeForms`

Original J6 wording said 3 actions: `list_templates`, `assign_to_appointment`, `get_responses`.
Real API doesn't have an "assign to appointment" concept — it's built around **sharing a form
with a patient** (SMS or portal), independent of any specific appointment.

**Real action set shipped:**

| Action | Endpoint(s) | Notes |
|---|---|---|
| `list_templates` | `GET /questionnaires` | straightforward |
| `create_template` | `POST /questionnaire` | added beyond the original 3; see validation hardening below |
| `get_patient_forms` | `GET /patients/{id}/questionnaires` | takes optional `appointment_id` filter — see below |
| `share_sms` | `POST /questionnaires/share/sms` | main "send it to the patient" action |
| `share_portal` | `POST /questionnaires/share/phr` | push into patient portal instead |
| `get_responses` | `GET /questionnaire/answer/{id}` | fetch filled-in answers |
| `get_responses_pdf` | `GET /questionnaire/answer/{id}/pdf` | shipped, not just nice-to-have |

**Deliberately excluded from this tool**: template edit/delete, signatures, flowsheet
integration, FHIR v2 — these read as practice-admin surface, not Receptionist-facing.

**RESOLVED — appointment-tied questionnaire assignment.** Confirmed against the real backend
(`AppointmentsBeanImpl.java`, `QuestionnaireUtil.java`): tying a questionnaire to a specific
appointment happens via the `questionnaire` array already accepted by `POST /appointments`
(create) and `PUT /appointment/{id}/reschedule` (reschedule) — the param `manageAppointments`
already exposed, not a new endpoint. Passing it writes a `PatientQuesMap` row with
`APPOINTMENT_ID` set and `IS_FILLED = false`. There's also a facility+provider+visit-type
default auto-assignment fallback when `questionnaire` is omitted on schedule, configured in a
legacy settings UI, not exposed via REST — documented as opaque behavior, not built against.

**RESOLVED — scope gotcha.** `share_sms`/`share_portal` explicitly hardcode
`APPOINTMENT_ID = null` server-side — they are **not appointment-scoped at all** and never will
be. Appointment-tied assignment only happens through `manageAppointments`'s `questionnaire`
param. Both tools' docstrings now say this explicitly: `manageAppointments` documents
`questionnaire=[{"questionnaire_id": ...}]` and points at `manageIntakeForms(action=
'list_templates')` to discover a valid ID first; `manageIntakeForms` defers appointment-tied
assignment to `manageAppointments` rather than implying `share_sms`/`share_portal` can do it.

**RESOLVED — discoverability.** `manageAppointments`'s `questionnaire` param used to be an
undocumented pass-through. Now documented directly in the `"schedule"` docstring, with the
two-call workflow spelled out: `list_templates` to get an ID, then either pass it into
`manageAppointments`'s `questionnaire` field (appointment-tied) or call `share_sms`/`share_portal`
directly (visit-independent).

**IMPLEMENTED.** `get_patient_forms` takes an optional `appointment_id` filter, hitting
`GET /patients/{id}/questionnaires?appointment_id={id}` — the read-side check for "has this
patient filled out the form for this specific visit."

**FIXED (previously listed here as open).** `manageAppointments`'s `"reschedule"` case was not
forwarding `questionnaire`/`consent_forms` into `reschedule_data`, even though `"schedule"` did
and the docstring claimed both were supported — a silent no-op, not an error. Now fixed in
`scheduling_tools.py`: both fields forward from `reschedule_data` the same way `schedule` does.
This landed after the original draft of this file said "worth a follow-up fix" — confirmed fixed
and documented in `CLAUDE.md`'s Known Pitfalls.

**Still genuinely open, not yet re-verified**: whether `/appointments`'s response echoes back
confirmation of which questionnaire was attached — the `"schedule"` response handling still just
does `strip_empty_values(response)` on the raw response, with no code specifically checking for a
questionnaire-confirmation field.

**Naming, resolved**: kept the real action names (`share_sms`/`share_portal`, `get_patient_forms`,
etc.) rather than the ticket's original `assign_to_appointment` wording — matches the real API
shape and avoids implying appointment-scoped assignment that doesn't exist.

---

## `create_template` validation hardening (added after the initial build)

Not in the original draft of this file — added as `create_template` got exercised more:

- **Array-stringification.** Models sometimes send `questions` (typed `List[Dict[str, Any]]`) as
  a JSON-encoded string instead of a native array, and FastMCP's Pydantic validation rejects a
  strict list type before the function body runs — the tool's own `{"error", "guidance"}`
  convention never gets a chance to help. Fixed by typing `questions` as
  `Union[str, List[Dict[str, Any]]]` and `json.loads()`-ing it when it arrives as a string.
- **`notes_type` legality per `questionnaire_type`.** The real API rejects illegal combinations
  with an opaque `HTTP 400`. The tool now pre-validates against the confirmed legal sets for all
  three creatable types (`General Questionnaire`, `Feedback Form`, `Pre-screening Form`), sourced
  from CharmHealth's actual Questionnaire Settings API reference doc — not guessed. `"Consent
  Form"` is not a real creatable type and was removed; `comments` is required, not optional.
- **`label_style` type mismatches produce an opaque `HTTP 500`, not a `400`.** A `font_size` sent
  as a string (`"16"`) instead of a number passed the old presence-only check and 500'd
  server-side. Fixed: pre-flight now coerces obviously-numeric strings and validates
  `font_size` (11–20) and the enum fields. `label_style` itself is now optional and defaulted to a
  plain look when omitted or partially specified — the native SwiftUI intake UI makes these style
  hints low-value, so forcing every caller to spell out all five sub-fields was pure friction.
  Only caller-supplied keys are validated.
- **FastMCP's schema check is shallow by design** — `Union[str, List[Dict[str, Any]]]` only
  enforces "some dict," nothing about keys/types/bounds. All of `notes_type` legality, conditional
  fields per `notes_type`, value ranges/enums, and length/count limits are hand-written pre-flight
  validation in the `create_template` case block — the actual line of defense against a model
  inventing plausible-but-wrong content, not the protocol-level schema.

## Billing endpoint confirmations

- **`send_balance_reminder` confirmed**: `POST /billing/statements/{id}/send` takes the
  `patient_id` directly in `{id}` — not a separately-generated `statement_id`, no
  statement-listing/creation step needed first. Previously flagged `TODO(confirm with Vibhu)`,
  now resolved.
- **`get_card_on_file` deliberately not shipped.** `/patients/{id}/carddetails` returns a raw,
  chargeable payment-gateway token and must never be wired into an LLM-facing action;
  `/patients/{id}/card_on_file` is the display-safe equivalent. A card-on-file action was pulled
  back out of scope pending a separate ticket/security review — charging a saved card is an
  explicit non-goal here.
- **`record_payment` deliberately not shipped** — pulled out of the `action` Literal and its case
  block entirely (not just left ungated): money movement, no settled gate tier, no
  revenue-cycle agent to test it through yet. cortex has a tripwire test guarding against it
  silently reappearing in the mutation catalog before the action itself comes back.

---

## Bug found while building (now fixed)

`manageAppointments` and `manageEncounter` (and, before it was fixed, `intake_forms.py`) share
the same pattern: `access_token`/`refresh_token`/`base_url`/`token_url` are initialized to `None`
before the `try` block that calls `get_http_headers()`, but `client_secret`/`accounts_server`
were not. If `get_http_headers()` raises (pure stdio mode, no HTTP headers at all), the exception
is swallowed but `client_secret` was never assigned, so the later
`CharmHealthAPIClient(..., client_secret=client_secret)` call throws
`UnboundLocalError: client_secret referenced before assignment`.

**Fixed in `billing.py` and `intake_forms.py`** (both now pre-initialize all six auth vars to
`None`). **Not yet fixed** in `manageAppointments`/`manageEncounter` (`scheduling_tools.py`/
`encounter_management.py`) or other older tool files — same two-line fix applies there; not
urgent since it only bites in pure-stdio mode with no headers at all.

---

## Folded into `CLAUDE.md`'s Known Pitfalls — where each item landed

Everything below has already been merged into the stable doc; this file is kept as the
discovery-log backtrack, not a duplicate source of truth.

| Discovery here | `CLAUDE.md` Known Pitfalls bullet |
|---|---|
| Mutation gating status for the new actions | "Mutations need a cortex-side gating decision, not just an MCP-side implementation" |
| `action_class` mapping for read actions | "The read-only actions also need an `action_class` entry in cortex's `policy.py`" |
| `send_balance_reminder` endpoint confirmation | "`managePatientBilling`'s `send_balance_reminder` endpoint — confirmed" |
| `get_card_on_file` exclusion | "Never wire `/patients/{id}/carddetails` into an LLM-facing tool action" |
| `share_sms`/`share_portal` not appointment-scoped | "`manageIntakeForms`'s `share_sms`/`share_portal` are NOT appointment-scoped" |
| `reschedule` not forwarding `questionnaire` | "Known bug, fixed" |
| `client_secret`/`accounts_server` unbound-variable bug | "`client_secret`/`accounts_server` unbound-variable risk in the auth-header block" |
| Array-stringification workaround | "LLMs sometimes stringify array-typed tool parameters" |
| `notes_type`/`questionnaire_type` legality | "`create_template` enforces `notes_type` legality per `questionnaire_type`" |
| `label_style`/`font_size` type coercion, 500 vs 400 | "A `label_style` field with the right keys but a wrong value *type* gets an opaque `HTTP 500`" |
| `label_style` defaulting | "`label_style` on `Label` questions is required by the real API but no longer required of the caller" |
| FastMCP shallow schema validation | "FastMCP's protocol-level schema check on `create_template` is shallow by design" |
