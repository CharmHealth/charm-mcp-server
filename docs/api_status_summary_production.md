# MCP Server API Status Summary — Production

Post-fix status for every tool/action tested against production. Full investigation detail, root
causes, and sandbox-vs-production diffs are in
[`api_probe_results_production.md`](api_probe_results_production.md) — this file is just the tables.

**⚠️ This run caused real side effects: a real SMS (`manageMessages`), a real SMS + portal share of an
intake form (`manageIntakeForms`), a real PHR invite (`managePatientFiles`), and a real questionnaire
template creation — all against the "Amy Test patient" record (`513000019594065`) in this production
account.**

## ✅ Working

| Tool | Action | Notes |
|---|---|---|
| findPatients | name search | |
| getPracticeInfo | facilities | |
| getPracticeInfo | providers | |
| manageIntakeForms | list_templates | |
| managePatient | update | |
| manageAppointments | list | |
| manageAppointments | schedule | |
| manageAppointments | reschedule (auto-fill) | |
| manageAppointments | reschedule (explicit fields) | |
| manageAppointments | cancel | |
| manageEncounter | create | |
| manageEncounter | list | |
| manageEncounter | review | |
| manageEncounter | sign | |
| manageEncounter | unlock | |
| managePatientVitals | list | |
| managePatientVitals | add | |
| managePatientVitals | update | |
| managePatientDrugs | list (medication) | |
| managePatientDrugs | list (supplement) | |
| managePatientDrugs | add (medication) | |
| managePatientDrugs | add (supplement, dosage as string) | |
| managePatientDrugs | update (medication) | |
| managePatientDrugs | discontinue (medication) | |
| managePatientDrugs | update (supplement) | |
| managePatientDrugs | discontinue (supplement) | |
| managePatientDrugs | prescribe (medication) | |
| managePatientAllergies | list | |
| managePatientAllergies | add | |
| managePatientAllergies | update | |
| managePatientAllergies | delete | |
| managePatientDiagnoses | list | |
| managePatientDiagnoses | add | |
| managePatientDiagnoses | update | |
| managePatientDiagnoses | delete | |
| managePatientRecalls | list | Differs from sandbox, where list also 401'd |
| managePatientFiles | send_phr_invite | Sends a real PHR invite |
| managePatientFiles | delete_photo | |
| managePatientFiles | upload_photo | |
| managePatientFiles | upload_id | |
| managePatientLabs | list | |
| manageTasks | list | |
| manageTasks | add | |
| manageTasks | update (status=Completed) | |
| manageTasks | update (status="In-progress") | **Works in production** — sandbox rejects this value |
| manageTasks | change_status (status=Completed) | |
| manageMessages | get_thread | |
| manageMessages | list | |
| manageMessages | send (channel=secure) | Correctly rejects when patient has no PHR account |
| manageMessages | send (channel=sms) | **Works in production** (sends a real SMS) — sandbox rejects, SMS not enabled there |
| managePatientBilling | get_balance | |
| managePatientBilling | list_invoices | |
| managePatientBilling | get_receipts | |
| manageIntakeForms | get_patient_forms | |
| manageIntakeForms | create_template | Creates a real, persistent template |
| manageIntakeForms | share_sms | **Works in production** (sends a real SMS) — 404s in sandbox |
| manageIntakeForms | share_portal | **Works in production** (real portal share) — 404s in sandbox |
| manageIntakeForms | get_responses | Correctly rejects invalid answer_id |

## ❌ Blocked

| Tool | Action | Reason |
|---|---|---|
| managePatientVitals | delete | Action doesn't exist in code (doc/code mismatch) — same as sandbox |
| managePatientNotes | list, add, delete (all actions) | `HTTP 401` "Unauthorized access" — same as sandbox, real OAuth-scope gap |
| managePatientRecalls | add | `HTTP 400 "Internal Error"` — same as sandbox |
| managePatientRecalls | delete | `HTTP 500 "Internal Error"` — sandbox got 401 instead; different failure mode, same net result |
| manageTasks | change_status (docstring's `new_status` param) | Param doesn't exist — doc/code mismatch, same as sandbox |
| manageMessages | send (channel=whatsapp) | `HTTP 404 "Invalid URL Passed"` — reproduces identically in both environments; genuinely nonexistent endpoint |
| **manageReferrals** | **create (direction=out), list, get, update, respond** | **`HTTP 401` "Unauthorized access" — NEW blocker not present in sandbox, where all of these work.** Production-only OAuth-scope/permission gap. |
| manageFax | send, status | Removed entirely — endpoints confirmed not in CharmHealth's documented API surface (commit `b654fe5`) |

## ⚠️ Inconclusive (data-dependent, needs more info to confirm)

| Tool | Action | Why unclear |
|---|---|---|
| managePatientDrugs | add (supplement, dosage as integer) | Same as sandbox — docstring says integer, schema requires string |
| managePatientBilling | send_balance_reminder | Same as sandbox — test patient has $0 balance, may be a correct rejection |
| manageIntakeForms | get_responses_pdf | Same as sandbox — no real completed form exists to test with a valid ID |
| manageReferrals | create (direction=in) | Test only asserts `isinstance(resp, dict)`, so it "passes" regardless of the underlying 401 — not a meaningful result given the create (direction=out) blocker above |
| managePatientLabs | order, get_details | Not exercised — no lab catalog lookup available, no existing lab results |
