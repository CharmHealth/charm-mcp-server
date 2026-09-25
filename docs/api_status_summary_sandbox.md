# MCP Server API Status Summary — Sandbox

Post-fix status for every tool/action tested. Full investigation detail, root causes, and fix history are in [`api_probe_results_sandbox.md`](api_probe_results_sandbox.md) — this file is just the tables.

## ✅ Working

| Tool | Action | Notes |
|---|---|---|
| findPatients | name search | |
| getPracticeInfo | facilities | |
| getPracticeInfo | providers | |
| managePatient | update | Fixed (missing `record_id`) |
| reviewPatientHistory | demographics | |
| manageAppointments | list | |
| manageAppointments | schedule | |
| manageAppointments | reschedule (auto-fill from appointment_id) | Fixed (wrong field name) |
| manageAppointments | reschedule (explicit fields) | |
| manageAppointments | cancel | |
| manageEncounter | create | |
| manageEncounter | list | |
| manageEncounter | review | |
| manageEncounter | sign | |
| manageEncounter | unlock | Fixed (duplicated URL prefix) |
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
| managePatientFiles | send_phr_invite | |
| managePatientFiles | delete_photo | |
| managePatientLabs | list | |
| manageTasks | list | |
| manageTasks | add | |
| manageTasks | update (status=Pending/Completed) | |
| manageTasks | change_status (status=Pending/Completed) | |
| manageMessages | get_thread | |
| manageMessages | list | |
| manageMessages | send (channel=secure) | Correctly rejects when patient has no PHR account |
| manageMessages | send (channel=sms) | Correctly rejects when SMS not enabled for practice |
| managePatientBilling | get_balance | |
| managePatientBilling | list_invoices | |
| managePatientBilling | get_receipts | |
| manageIntakeForms | list_templates | |
| manageIntakeForms | get_patient_forms | |
| manageIntakeForms | create_template | |
| manageIntakeForms | get_responses | Correctly rejects invalid answer_id |
| manageReferrals | create (direction=out) | |
| manageReferrals | list (direction=out) | |
| manageReferrals | get (direction=out) | |
| manageReferrals | respond (direction=out) | |

## ❌ Blocked

| Tool | Action | Reason |
|---|---|---|
| managePatientVitals | delete | Action doesn't exist in code (`Literal["add","list","update"]`) despite docstring — doc/code mismatch |
| managePatientNotes | list, add, delete (all actions) | `HTTP 401` — HTML login/error page instead of JSON. Likely missing OAuth scope |
| managePatientRecalls | list, delete | `HTTP 401` — "Unauthorized access" HTML page. Likely missing OAuth scope |
| managePatientRecalls | add | `HTTP 400 "Internal Error"` |
| managePatientFiles | upload_photo, upload_id | Crash fixed (was `files=` kwarg bug); backend still rejects with "Please upload an image" regardless of field name tried — real field name unconfirmed without CharmHealth docs |
| manageTasks | update / change_status (status="In-progress") | Backend rejects this specific status value on every endpoint (empty `HTTP 400`) — real value unknown; `"Pending"`/`"Completed"` work fine |
| manageTasks | change_status (docstring's `new_status` param) | Param doesn't exist — doc/code mismatch (`status` is correct) |
| manageMessages | send (channel=whatsapp) | `HTTP 404 "Invalid URL Passed"` — endpoint likely doesn't exist (same signature as removed `manageFax`) |
| manageIntakeForms | share_sms, share_portal | `HTTP 404 "Invalid URL Passed"` — same as above |
| manageFax | send, status | **Removed entirely** — endpoints confirmed not in CharmHealth's documented API surface (commit `b654fe5`) |

## ⚠️ Inconclusive (data-dependent, needs more info to confirm)

| Tool | Action | Why unclear |
|---|---|---|
| managePatientDrugs | add (supplement, dosage as integer) | Docstring says use integer; schema requires string — works fine as string, only the docstring example is wrong |
| managePatientBilling | send_balance_reminder | Fails, but test patient has $0 balance — may be correct rejection, not a bug |
| manageIntakeForms | get_responses_pdf | Same "Invalid URL Passed" signature as confirmed bugs, but no real completed form exists to test with a valid ID |
| manageReferrals | update (direction=out) | Fails on a self-referral (this sandbox has only 1 provider) — may be a real restriction, not a bug |
| manageReferrals | create (direction=in) | Same self-referral caveat; inconsistent with direction=out create succeeding |
| managePatientLabs | order, get_details | Not exercised — no lab catalog lookup available, no existing lab results |
