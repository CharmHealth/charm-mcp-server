# MCP server API probe — production results

Same probe suite as [`api_probe_results_sandbox.md`](api_probe_results_sandbox.md) (CH-907), re-run
file-by-file against the running server (`MCP_SERVER_URL=http://127.0.0.1:8000/mcp/`) after pointing
its `.env` at production CharmHealth credentials instead of sandbox. Sandbox's test entities
(Ahmed Choi / Peter Parker / a specific facility+questionnaire) don't exist in this account, so each
probe file's hardcoded IDs were swapped for production equivalents — sandbox line commented out
directly above, production line active:

- Patient: **Amy Test patient** — `patient_id: 513000019594065` (chosen over "ABCD Test" after
  confirming with Sumana; synthetic contact info)
- Provider: **Sumana Ramanathan** — `member_id: 513000035213007` (her own real physician account on
  this practice, chosen over a "Test accnt" provider)
- Facility: **Charm Clinic** — `facility_id: 513000030839375` (exact name match found via
  `getPracticeInfo`, unlike patient/provider no substitute was needed)
- Questionnaire: **Insurance** — `questionnaire_id: 513000033416055` (a real pre-existing template,
  standing in for sandbox's "Pre-Visit Symptom Check" which doesn't exist here)

**⚠️ Real side effects from this run — not reversible:**
- `manageMessages send (channel=sms)` actually sent a real SMS ("MCP API probe test message - sms
  channel") to Amy Test patient's mobile (`8558786789`) — sandbox correctly rejects this (SMS not
  enabled there), production has it enabled.
- `manageIntakeForms share_sms` and `share_portal` both succeeded — a real SMS and a real patient
  portal share of an intake form were sent to the same patient. Both 404 in sandbox.
- `manageIntakeForms create_template` created a real questionnaire template ("MCP API probe test
  template") that now persists in the production account's template list.
- `managePatientFiles send_phr_invite` sent a real PHR/portal invite to Amy Test patient.

Command format: `MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run pytest tests/test_api/test_<toolName>_api.py -v -s`

## core_tools.py

| Tool | Action | Result | Notes |
|---|---|---|---|
| findPatients | name search ("Ahmed Choi") | ✅ PASS (0 results) | Confirms sandbox's test patient doesn't exist here — expected, not a bug. |
| findPatients | name search ("Test") | ✅ PASS | 10+ synthetic test patients found; picked Amy Test patient per Sumana's choice. |
| getPracticeInfo | facilities | ✅ PASS | 28 facilities returned, including an exact "Charm Clinic" match. |
| getPracticeInfo | providers | ✅ PASS | 45 providers returned (mix of real-looking and clearly fake names — Doctor Strange, Gregory House, etc. — this account is a shared demo/test tenant on the production API cluster). |
| manageIntakeForms | list_templates | ✅ PASS | 50 real templates returned (paginated); no "Pre-Visit Symptom Check" — picked "Insurance" as the stand-in. |

## patient_management.py

Pytest file: `tests/test_api/test_managePatient_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatient | update | ✅ PASS | Confirms the sandbox `record_id` fix (commit `9c6b98d`) also works correctly against production. |

## scheduling_tools.py

Pytest file: `tests/test_api/test_manageAppointments_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageAppointments | list | ✅ PASS | |
| manageAppointments | schedule | ✅ PASS | |
| manageAppointments | reschedule (auto-fill) | ✅ PASS | Confirms the sandbox `patient_id` field-name fix also works in production. |
| manageAppointments | reschedule (explicit fields) | ✅ PASS | |
| manageAppointments | cancel | ✅ PASS | |

All 5/5 pass — no regressions from the sandbox fixes.

## encounter_management.py

Pytest file: `tests/test_api/test_manageEncounter_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageEncounter | create | ✅ PASS | |
| manageEncounter | list | ✅ PASS | |
| manageEncounter | review | ✅ PASS | |
| manageEncounter | sign | ✅ PASS | |
| manageEncounter | unlock | ✅ PASS | Confirms the sandbox URL-prefix fix (commit `9c6b98d`) also works in production — no longer irreversible via this tool. |

All 5/5 pass.

## clinical_data.py

Pytest files: `test_managePatientVitals_api.py`, `test_managePatientDrugs_api.py`, `test_managePatientAllergies_api.py`, `test_managePatientDiagnoses_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientVitals | list | ✅ PASS | |
| managePatientVitals | add | ✅ PASS | |
| managePatientVitals | update | ✅ PASS | |
| managePatientVitals | delete (doc/code mismatch check) | ✅ PASS | Same mismatch as sandbox: `Literal["add","list","update"]` still doesn't include `"delete"` despite the docstring — confirms it's a code issue, not environment-specific. |
| managePatientDrugs | list/add/update/discontinue (medication + supplement), prescribe | ✅ PASS (9/9) | |
| managePatientDrugs | add (supplement, dosage as integer) | ✅ PASS (documents mismatch) | Same doc/code mismatch as sandbox — docstring says use an integer, schema requires string. |
| managePatientAllergies | list/add/update/delete | ✅ PASS (4/4) | |
| managePatientDiagnoses | list/add/update/delete | ✅ PASS (4/4) | |

**clinical_data.py: 22/22 pass — fully consistent with sandbox, no environment-specific differences.**

## clinical_support.py

Pytest files: `test_managePatientNotes_api.py`, `test_managePatientRecalls_api.py`, `test_managePatientFiles_api.py`, `test_managePatientLabs_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientNotes | list | ❌ **FAIL** | Same `HTTP 401` "Unauthorized access" HTML as sandbox — reproduces identically in production, confirming this is a real OAuth-scope gap on this integration, not a sandbox-only provisioning issue. |
| managePatientNotes | add | ❌ **FAIL** | Same. |
| managePatientNotes | delete | ❌ **FAIL** | Same. |
| managePatientRecalls | list | ✅ **PASS** | **Differs from sandbox**, where `list` also 401'd. In production, `list` works but `add`/`delete` still don't (see below) — the auth gap here is narrower than in sandbox. |
| managePatientRecalls | add | ❌ **FAIL** | `HTTP 400 {"code":"6","message":"Internal Error"}` — same failure signature as sandbox. |
| managePatientRecalls | delete | ❌ **FAIL** | `HTTP 500 {"code":"1000","message":"Internal Error"}` — **differs from sandbox**, which got a 401 "Unauthorized access" HTML for delete. Different failure mode, same net result (broken). |
| managePatientFiles | send_phr_invite | ✅ PASS | Real PHR invite sent to Amy Test patient. |
| managePatientFiles | delete_photo | ✅ PASS | |
| managePatientFiles | upload_photo | ✅ PASS | Confirms the sandbox multipart/form-data fix (commit `b89bf18`) works end-to-end in production — sandbox's lingering "please upload an image" field-name mystery did not reproduce here. |
| managePatientFiles | upload_id | ✅ PASS | Same. |
| managePatientLabs | list | ✅ PASS | |

**Net: notes fully blocked (matches sandbox); recalls partially blocked but differently shaped than sandbox; files and labs fully working (matches/improves on sandbox).**

## task_management.py

Pytest file: `tests/test_api/test_manageTasks_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageTasks | list | ✅ PASS | |
| manageTasks | add | ✅ PASS | |
| manageTasks | update (status=Completed) | ✅ PASS | |
| manageTasks | update (status="In-progress") | ❌ **FAIL (test regressed, in a good way)** | This test asserts the sandbox-confirmed bug (`"In-progress"` rejected with an empty `HTTP 400`). In production, the same call **succeeds**: `{"code": "0", "message": "success", ...}`. Real, confirmed environment difference — production's task backend accepts a status value sandbox's doesn't. Not a code bug; the test itself needs a production-aware assertion if this suite is kept running against prod going forward. |
| manageTasks | change_status (status=Completed) | ✅ PASS | |
| manageTasks | change_status (docstring's `new_status` param) | ✅ PASS (documents mismatch) | Same doc/code mismatch as sandbox — `new_status` isn't a real parameter. |

## communication.py

Pytest file: `tests/test_api/test_manageMessages_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageMessages | get_thread | ✅ PASS | |
| manageMessages | list | ✅ PASS | |
| manageMessages | send (channel=secure) | ✅ PASS (correct rejection) | Same as sandbox: Amy Test patient has no PHR account. |
| manageMessages | send (channel=sms) | ❌ **FAIL (real side effect)** | Test asserts sandbox's rejection ("Bidirectional sms is not enabled"). In production this **succeeded** and sent a real SMS: `{"code": "0", "message": "Message sent successfully", ...}`. Confirmed real environment difference — SMS is enabled for this production practice. |
| manageMessages | send (channel=whatsapp) | ❌ **FAIL** | Same `HTTP 404 {"code":5,"message":"Invalid URL Passed"}` as sandbox — reproduces identically, reinforcing that this is a genuinely nonexistent/undocumented endpoint (same conclusion as the removed `manageFax`), not a sandbox provisioning gap. |

## billing.py

Pytest file: `tests/test_api/test_managePatientBilling_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientBilling | get_balance | ✅ PASS | |
| managePatientBilling | list_invoices | ✅ PASS | |
| managePatientBilling | get_receipts | ✅ PASS | |
| managePatientBilling | send_balance_reminder | ✅ PASS (documents inconclusive) | Same as sandbox — inconclusive due to $0 balance, not asserted as a bug. |

All 4/4 pass, matching sandbox.

## intake_forms.py

Pytest file: `tests/test_api/test_manageIntakeForms_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageIntakeForms | list_templates | ✅ PASS | 50 real templates (paginated), unlike sandbox's 13. |
| manageIntakeForms | get_patient_forms | ✅ PASS | Empty (no forms shared with Amy Test patient prior to this run) — correct. |
| manageIntakeForms | create_template | ✅ PASS | Created a real template end-to-end — **persists in the production account.** |
| manageIntakeForms | share_sms | ✅ **PASS (real side effect)** | **Differs from sandbox**, which 404'd with "Invalid URL Passed". In production this succeeded and sent a real SMS with the intake form link to Amy Test patient. |
| manageIntakeForms | share_portal | ✅ **PASS (real side effect)** | Same — succeeded here, 404'd in sandbox. A real patient-portal form share was sent. |
| manageIntakeForms | get_responses (invalid id) | ✅ PASS (correct rejection) | Same clean rejection as sandbox. |
| manageIntakeForms | get_responses_pdf (invalid id) | ✅ PASS (documents inconclusive) | Same as sandbox. |

All 7/7 pass. **Together with `manageMessages`'s whatsapp result above, this resolves the sandbox report's open question:** share_sms/share_portal working here (while whatsapp still 404s in both environments) confirms those two were a sandbox-specific provisioning gap, not the same "endpoint doesn't really exist" story as whatsapp/fax.

## referrals.py

Pytest file: `tests/test_api/test_manageReferrals_api.py`

**This is the one tool file that regressed relative to sandbox — entirely blocked here, fully working there.**

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageReferrals | create (direction=out) | ❌ **FAIL** | `HTTP 401` "Unauthorized access" HTML — same signature as `managePatientNotes`/partial `managePatientRecalls`. **Worked fine in sandbox.** |
| manageReferrals | list (direction=out) | ❌ **FAIL** | Same 401 — fails independently of create. |
| manageReferrals | get (direction=out) | ❌ **FAIL** | Depends on `_create_referral_out()` helper, which itself asserts and fails first (401). |
| manageReferrals | update (direction=out, inconclusive) | ❌ **FAIL** | Same — the helper's own assertion fails before this test's "always true" check is reached. |
| manageReferrals | respond (direction=out) | ❌ **FAIL** | Same — helper fails first. |
| manageReferrals | create (direction=in, inconclusive) | ✅ PASS (trivially) | Doesn't use the helper and only asserts `isinstance(resp, dict)`, so it "passes" regardless of the underlying 401 — not a meaningful signal either way. |

**5/6 fail. Real finding: this production integration appears to be missing whatever OAuth scope/permission `manageReferrals` needs, even though the exact same calls work cleanly in sandbox.** Worth checking with whoever manages the production CharmHealth app registration — this is very likely the same class of gap as `managePatientNotes`'s full block and `managePatientRecalls`'s partial one, just scoped differently per environment.

---

# Summary: all 16 pytest files re-run against production

Findings ranked by impact:

1. **🚨 New blocker not present in sandbox: `manageReferrals` entirely non-functional in production** (`HTTP 401` "Unauthorized access" on create/list — cascades to get/update/respond). The exact opposite of sandbox, where all of referrals worked (aside from the already-documented inconclusive self-referral findings). Needs a production OAuth-scope/permission fix before this tool can be used for real in this environment.
2. **⚠️ Real, irreversible side effects occurred during this run** — a real SMS via `manageMessages`, a real SMS + real portal share via `manageIntakeForms`, a real PHR invite via `managePatientFiles`, and a real questionnaire template creation — all against the Amy Test patient record and this production account. See the callout at the top of this file.
3. **Confirmed: all 4 sandbox code-bug fixes (commit `9c6b98d`, `b89bf18`) work correctly in production too** — `managePatient` update, `manageAppointments` reschedule auto-fill, `manageEncounter` unlock, `managePatientFiles` upload_photo/upload_id. No regressions.
4. **Confirmed as genuinely broken/nonexistent (not environment-specific):** `manageMessages` send/whatsapp and, together with intake forms' opposite result, this narrows the earlier "systemic pattern" theory from the sandbox report — whatsapp is the real dead endpoint; share_sms/share_portal were just a sandbox provisioning gap.
5. **Auth-scope gaps, partially environment-specific:** `managePatientNotes` (fully blocked in both), `managePatientRecalls` (list now works in prod, add/delete still broken with different error codes than sandbox), `manageReferrals` (fully blocked in prod only, see #1).
6. **Confirmed environment-specific business-rule differences (not bugs):** production has SMS enabled for `manageMessages` (sandbox doesn't); production accepts task `status="In-progress"` (sandbox rejects it).
7. **Doc/code mismatches carry over unchanged from sandbox:** `managePatientVitals` delete action, `managePatientDrugs` add-supplement dosage type, `manageTasks` change_status's `new_status` param — same in both environments, confirming these are pure code/docstring issues, not environment artifacts.
8. **Inconclusive, unchanged from sandbox:** `managePatientBilling` send_balance_reminder, `manageIntakeForms` get_responses_pdf.

All pytest files are under `tests/test_api/test_<toolName>_api.py`, each with sandbox IDs commented out directly above the active production IDs — runnable against either environment by swapping which line is active, or against whichever backend the running server's `.env` currently points to.
