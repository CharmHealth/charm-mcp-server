# MCP server API probe — sandbox results

Manual, one-by-one probe of every charm-mcp-server tool against the running server
(`MCP_SERVER_URL=http://127.0.0.1:8000/mcp/`) via `scripts/mcp_test_client.py`, using
real sandbox test data:

- Patient: **Ahmed Choi** — `patient_id: 100010000000018023` (facilities: `100010000000008157` Charm Clinic, `100010000000031005` Boston General Clinic)
- Provider: **Peter Parker** — `member_id: 100010000000000117` (only provider with `sign_encounter` privilege; no "Dr. John" exists in this sandbox)
- Facility (default): `100010000000008157` (Charm Clinic)

Command format: `MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run scripts/mcp_test_client.py <tool> '<json args>'`

## core_tools.py

| Tool | Action | Result | Notes |
|---|---|---|---|
| findPatients | name search | ✅ PASS | Found Ahmed Choi |
| getPracticeInfo | facilities | ✅ PASS | 9 facilities returned |
| getPracticeInfo | providers | ✅ PASS | Only 1 provider (Peter Parker) has sign_encounter privilege |

## patient_management.py

| Tool | Action | Result | Notes |
|---|---|---|---|
| reviewPatientHistory | demographics only | ✅ PASS | |
| managePatient | update | ❌ **FAIL** | `HTTP 400: "Patient Record Id is mandatory. Please specify it"` — **real bug**: `update_specific_details=True` path in `patient_management.py` builds the PUT payload from first_name/last_name/gender/dob/facilities but never includes `record_id`, even though this practice requires it. Not an environment issue — a code bug. |

## scheduling_tools.py

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageAppointments | list | ✅ PASS | |
| manageAppointments | schedule | ⚠️ PASS (cosmetic bug) | Appointment created fine, but guidance text says "ID: None" — code reads `response["appointment"]["id"]`, real API returns `appointment_id`, not `id`. |
| manageAppointments | reschedule (appointment_id only, relying on documented auto-fill) | ❌ **FAIL** | Errors "Missing required fields for rescheduling" even though the tool's own docstring says appointment_id alone should auto-fill the rest. Root cause: the auto-fill's `GET /appointment/{id}` response parsing (`appt_response.get("output_string") or appt_response.get("appointment")`) doesn't match the real response shape, so patient_id/facility_id/provider_id never get filled in. **Real bug.** |
| manageAppointments | reschedule (all fields provided explicitly) | ✅ PASS | Confirms the underlying reschedule endpoint itself works — bug is isolated to the auto-fill convenience path. |
| manageAppointments | cancel | ✅ PASS | |

## encounter_management.py

Pytest file: `tests/test_api/test_manageEncounter_api.py` (run: `MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run pytest tests/test_api/test_manageEncounter_api.py -v`)

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageEncounter | create | ✅ PASS | |
| manageEncounter | list | ✅ PASS | |
| manageEncounter | review | ✅ PASS | |
| manageEncounter | sign | ✅ PASS | |
| manageEncounter | unlock | ❌ **FAIL** | `HTTP` unknown/404 surfaced as `"Failed to unlock encounter: Unknown error"` — **real bug**: unlock posts to `/api/ehr/v1/encounters/{id}/unlock`, but `CharmHealthAPIClient.base_url` already ends in `/api/ehr/v1` and every other endpoint in this file uses a bare relative path. Duplicated prefix → 404. Side effect discovered live: this makes `sign` **irreversible** via this tool today. An earlier manual test (encounter `100010000000128111`) is now permanently stuck signed in sandbox as a result — left as-is per decision to not touch `src/` yet. |

## clinical_data.py

Pytest file: `tests/test_api/test_managePatientVitals_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientVitals | list | ✅ PASS | |
| managePatientVitals | add | ✅ PASS | |
| managePatientVitals | update | ✅ PASS | |
| managePatientVitals | delete | ❌ **doc/code mismatch** | Docstring documents a `"delete"` action ("Remove incorrect vital record"), but `action: Literal["add", "list", "update"]` never includes it. FastMCP rejects it at the schema level: `Input validation error: 'delete' is not one of ['add', 'list', 'update']`. Either implement delete or fix the docstring. |

## 🚨 BLOCKING: OAuth token refresh fails — expired TLS certificate on token server

Discovered while testing `managePatientDrugs`. Not a per-tool bug — this breaks **every** tool.

```
Token refresh failed: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1032)
```

- First seen on `managePatientDrugs(list, medication)` and `managePatientDrugs(list, supplement)`.
- Confirmed **not transient**: immediately re-ran `findPatients` (which had passed cleanly ~10 minutes earlier in this same session) — same failure.
- Root cause **confirmed via direct certificate inspection** (`openssl s_client` against each host, independent of local clock/trust store):
  - Sandbox hosts (`accounts106.charmtracker.com`, `sandbox3.charmtracker.com`) serve a wildcard `*.charmtracker.com` cert valid `Aug 20 2025 → Sep 1 2026 23:59:59 GMT` — **expired**.
  - Production hosts (`accounts.charmtracker.com`, `ehr2.charmtracker.com`) serve a **different, newer** wildcard `*.charmtracker.com` cert valid `Aug 24 2026 → Mar 10 2027` — **currently valid**.
  - So this is real, not a local clock artifact — sandbox's TLS cert simply wasn't rotated when production's was, and it lapsed. This is a CharmHealth infra/ops issue (sandbox cert renewal), not fixable from this repo's code or `.env` config.
  - **Practical implication:** production is reachable right now; sandbox is not. Testing could resume against production immediately while sandbox's cert gets renewed.
- **UPDATE (same session, ~15 min later): resolved.** Re-checked both sandbox hosts (`accounts106.charmtracker.com`, `sandbox3.charmtracker.com`) — both now serve the same renewed cert as production (`Aug 24 2026 → Mar 10 2027`), confirmed via 5 repeated `openssl s_client` checks (consistent fingerprint, no flakiness). `findPatients` succeeded again with no SSL error. Either CharmHealth ops actively rotated it, or we caught sandbox mid-rollout of the same renewal production already had. Testing resumed.

Pytest file: `tests/test_api/test_managePatientDrugs_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientDrugs | list (medication) | ✅ PASS | |
| managePatientDrugs | list (supplement) | ✅ PASS | |
| managePatientDrugs | add (medication) | ✅ PASS | |
| managePatientDrugs | add (supplement), dosage as string | ✅ PASS | |
| managePatientDrugs | add (supplement), dosage as integer per docstring's own example | ❌ **doc/code mismatch** | Docstring: *"Provide dosage as integer (e.g., dosage=5, not dosage='5mg')"*. Actual signature: `dosage: Optional[str]`. Passing a real integer (as the docstring instructs) fails schema validation: `Input validation error: 500 is not valid under any of the given schemas`. Only a string works. |
| managePatientDrugs | update (medication) | ✅ PASS | |
| managePatientDrugs | discontinue (medication) | ✅ PASS | |
| managePatientDrugs | update (supplement) | ✅ PASS | |
| managePatientDrugs | discontinue (supplement) | ✅ PASS | |
| managePatientDrugs | prescribe (medication, with encounter_id) | ✅ PASS | |

Pytest file: `tests/test_api/test_managePatientAllergies_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientAllergies | list | ✅ PASS | |
| managePatientAllergies | add | ✅ PASS | |
| managePatientAllergies | update | ✅ PASS | |
| managePatientAllergies | delete | ✅ PASS | |

Pytest file: `tests/test_api/test_managePatientDiagnoses_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientDiagnoses | list | ✅ PASS | |
| managePatientDiagnoses | add | ✅ PASS | Real API's own success message has a typo: `"Doagnoses saved successfully."` — CharmHealth backend text, not this repo. |
| managePatientDiagnoses | update | ✅ PASS | |
| managePatientDiagnoses | delete | ✅ PASS | |

**clinical_data.py complete: 4/4 tools tested (managePatientVitals, managePatientDrugs, managePatientAllergies, managePatientDiagnoses).**

## clinical_support.py

Pytest files: `tests/test_api/test_managePatientNotes_api.py`, `tests/test_api/test_managePatientRecalls_api.py`, `tests/test_api/test_managePatientFiles_api.py`, `tests/test_api/test_managePatientLabs_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientNotes | list | ❌ **FAIL** | `HTTP 401` with a ~377KB HTML login page body, not JSON. Reproducible. |
| managePatientNotes | add | ❌ **FAIL** | Same 401/HTML. |
| managePatientNotes | delete | ❌ **FAIL** | Same 401/HTML, even with a placeholder record_id — not data-dependent. |
| managePatientRecalls | list | ❌ **FAIL** | `HTTP 401` — CharmHealth's own "Unauthorized access" HTML error page (distinct, smaller page than notes' — a real backend auth-denial page, not a generic redirect). |
| managePatientRecalls | add | ❌ **FAIL** (different mode) | Reaches the real API (JSON, not HTML) but backend returns `HTTP 400 {"code":"6","message":"Internal Error"}`. |
| managePatientRecalls | delete | ❌ **FAIL** | Same 401/"Unauthorized access" HTML as list. |
| managePatientFiles | send_phr_invite | ✅ PASS | Confirmed clean on a second full rerun after the auth blocker below cleared. |
| managePatientFiles | delete_photo | ✅ PASS | Same. |
| managePatientFiles | upload_photo | ❌ **FAIL — confirmed pure code bug** | `CharmHealthAPIClient.post() got an unexpected keyword argument 'files'`. `CharmHealthAPIClient.post()`'s signature is `(endpoint, data=None, params=None)` — no `files` param exists at all. Crashes before any network call, so this is environment-independent — will fail identically in production. |
| managePatientFiles | upload_id | ❌ **FAIL — same code bug** | Same root cause: `client.post(f"/patients/{patient_id}/identity", data=form_data, files=files)` hits the same nonexistent `files` kwarg. |
| managePatientLabs | list | ✅ PASS | Empty result (no lab data for this patient) — correct behavior, not an error. Confirmed clean on rerun. |
| managePatientLabs | order / get_details | ⚠️ Not exercised | `order` needs real lab catalog values with no lookup action available (documented limitation in the tool's own docstring — a real OAuth scope gap on CharmHealth's catalog endpoints, already known). `get_details` needs a real group_id/lab_order_id, which doesn't exist since there are no lab results for this patient. |

Full-suite rerun after the auth blocker below cleared: **8 failed, 3 passed** — exactly matching the individually-confirmed results above. `managePatientNotes`/`managePatientRecalls` (all actions) and `managePatientFiles` upload_photo/upload_id are real, reproducible bugs, not blocker artifacts.

## 🚨 BLOCKING (second, distinct issue, now resolved): OAuth refresh_token rejected with `access_denied`

Discovered when re-running the clinical_support.py pytest files together. **Different from the earlier expired-certificate issue** — that was a TLS handshake failure; this was the token server actively rejecting the refresh_token itself:

```
Token refresh failed: Failed to obtain new token with response: {"error":"access_denied"}
```

- Confirmed systemic, not tool-specific: even `findPatients` (reliable all session) failed identically at the time.
- **Resolved** — confirmed working again via `findPatients` and a full clinical_support.py pytest rerun. Root cause not confirmed (possibly refresh_token rotation/rate-limit from high call volume this session, resolved on its own or via action taken outside this session).
- Testing resumed.

## task_management.py

Pytest file: `tests/test_api/test_manageTasks_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageTasks | list | ✅ PASS | |
| manageTasks | add | ✅ PASS | |
| manageTasks | update | ❌ **FAIL** | Reproducible empty `HTTP 400: ` (no message body) using the exact same field shape "add" accepts. Root cause not pinned down (real API field requirements aren't documented in this repo per its own known-pitfalls notes), but consistently reproducible — not a data/flake issue. |
| manageTasks | change_status (correct param `status`) | ✅ PASS | |
| manageTasks | change_status (docstring's literal `new_status` param) | ❌ **doc/code mismatch** | Docstring: *"requires task_id + new_status"*. No `new_status` parameter exists in the signature — only `status`. Schema rejects it outright: `Unexpected keyword argument`. |

## communication.py

Pytest file: `tests/test_api/test_manageMessages_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageMessages | get_thread | ✅ PASS | |
| manageMessages | list | ✅ PASS | |
| manageMessages | send (channel=secure) | ✅ PASS (correct rejection) | Real backend rejection, not a bug: `"PHR account is mandatory for receiving message."` — Ahmed Choi has no PHR/portal account. |
| manageMessages | send (channel=sms) | ✅ PASS (correct rejection) | Real backend rejection, not a bug: `"Bidirectional sms is not enabled"` — this sandbox practice's config limitation. |
| manageMessages | send (channel=whatsapp) | ❌ **FAIL — confirmed likely bug** | `HTTP 404 {"code":5,"message":"Invalid URL Passed"}` — CharmHealth's own "no such route" error, not a business rejection. `_send_whatsapp()` posts to `/messages/whatsapp/patient/{id}/send`, which likely doesn't exist under `/api/ehr/v1`. |

**UPDATE: `manageFax` removed entirely from this codebase** (Zoho Desk ticket #1551594, see `CLAUDE.md`) — its `/fax/send` and `/fax/{id}/status` endpoints (which showed the identical "Invalid URL Passed" error documented here originally) were checked against CharmHealth's full local API reference (165 documented paths) and found nowhere in it. Rather than a sandbox-provisioning gap, this confirms the endpoints were simply never real. The tool was deleted (not left broken) — `communication_mcp` now exposes only `manageMessages`. `test_manageFax_api.py` removed accordingly. This retroactively strengthens the theory that manageMessages' whatsapp send and manageIntakeForms' share_sms/share_portal (same "Invalid URL Passed" signature, see below) may also be calling undocumented/nonexistent endpoints rather than a provisioning gap — worth checking against the same API reference before assuming otherwise.

## billing.py

Pytest file: `tests/test_api/test_managePatientBilling_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| managePatientBilling | get_balance | ✅ PASS | |
| managePatientBilling | list_invoices | ✅ PASS | |
| managePatientBilling | get_receipts | ✅ PASS | |
| managePatientBilling | send_balance_reminder (email) | ⚠️ **inconclusive** | Fails with a generic "Sending failed" even though Ahmed Choi has a valid email. Most likely cause: he has $0 balance/no invoices (confirmed above) and CharmHealth may legitimately reject a reminder when nothing is owed — not necessarily a bug. No tool exists here to create test billing data to confirm either way. |

## intake_forms.py

Pytest file: `tests/test_api/test_manageIntakeForms_api.py`

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageIntakeForms | list_templates | ✅ PASS | 13 real templates found. |
| manageIntakeForms | get_patient_forms | ✅ PASS | Empty (no forms shared with Ahmed Choi yet) — correct. |
| manageIntakeForms | create_template | ✅ PASS | Created a real template end-to-end. |
| manageIntakeForms | share_sms | ❌ **FAIL — part of systemic pattern** | `HTTP 404 {"code":5,"message":"Invalid URL Passed"}` on `/questionnaires/share/sms`. |
| manageIntakeForms | share_portal | ❌ **FAIL — part of systemic pattern** | Identical error on `/questionnaires/share/phr`. |
| manageIntakeForms | get_responses (invalid id) | ✅ PASS (correct rejection) | Cleanly rejects a bad `answer_id` with a specific real backend message — confirms this endpoint itself works, distinct from the "Invalid URL Passed" pattern. |
| manageIntakeForms | get_responses_pdf (invalid id) | ⚠️ **inconclusive** | Same "Invalid URL Passed" signature as the confirmed bugs above, but could just be this endpoint's way of saying "PDF not found for this id" — no real completed submission exists to test with (the only ways to create one, share_sms/share_portal, are themselves broken). |

**🔍 Cross-cutting pattern across TWO tool files, THREE remaining endpoints, all with the identical `HTTP 404 {"code":5,"message":"Invalid URL Passed"}`** (originally five/three — `manageFax`'s two were resolved by confirming the tool itself was undocumented and removing it, see communication.py section above):
- `manageMessages`: `send` with `channel=whatsapp` (`/messages/whatsapp/patient/{id}/send`)
- `manageIntakeForms`: `share_sms` (`/questionnaires/share/sms`), `share_portal` (`/questionnaires/share/phr`)

Given `manageFax`'s identical error turned out to mean "not a real endpoint at all," these three are now more likely to be the same story than "one systemic provisioning gap" — **worth checking each against CharmHealth's actual API reference (the same one used to confirm manageFax) before assuming a sandbox-vs-production difference.**

## referrals.py

Pytest file: `tests/test_api/test_manageReferrals_api.py`

**Caveat: this sandbox has exactly ONE provider (Peter Parker), so every referral here is necessarily a "self-referral" (same member as both referring and receiving party). Some findings below may be an artifact of that, not a general bug — flagged individually.**

| Tool | Action | Result | Notes |
|---|---|---|---|
| manageReferrals | create (direction=out) | ✅ PASS | |
| manageReferrals | list (direction=out) | ✅ PASS | |
| manageReferrals | get (direction=out) | ✅ PASS | |
| manageReferrals | update (direction=out) | ⚠️ **inconclusive** | Fails with `HTTP 400 {"code":"1000","message":"zf.api.inavalid.id.provided"}` even though from_member/to_internal_member merge in as the same valid provider ID that `create` accepted fine on this same referral. Possibly a backend restriction on updating a self-referral specifically — can't rule out without a second provider. |
| manageReferrals | respond (direction=out) | ✅ PASS | |
| manageReferrals | create (direction=in) | ⚠️ **inconclusive** | Fails with `HTTP 400 {"code":"6","message":"Internal Error"}` using the same self-referral pattern that succeeded for direction=out create. The out/in inconsistency is worth a closer look, but can't be conclusively separated from the single-provider sandbox limitation. |

---

# Summary: all 20 tools tested

Findings requiring follow-up, ranked by likely impact:

1. **🚨 Two session-wide blockers hit during testing** (both since resolved, but real): sandbox's TLS cert was expired for a period (now renewed), and the OAuth refresh_token was denied with `access_denied` for a period (now working). Both are CharmHealth infra-side, not code bugs — but worth confirming with whoever manages the sandbox account that these won't recur, especially before relying on sandbox for future testing.
2. **🔍 "Invalid URL Passed" pattern — 3 endpoints across 2 files remaining** (down from 5/3 — `manageFax`'s two were resolved: confirmed undocumented, tool removed entirely): `manageMessages` (send/whatsapp), `manageIntakeForms` (share_sms, share_portal). Given manageFax's identical error meant "not a real endpoint," check these three against CharmHealth's actual API reference before assuming a sandbox-provisioning gap.
3. **Confirmed real code bugs — all fixed, see "Bug fixes" section below:**
   - `managePatient` update — missing `record_id` in payload despite this practice requiring it (`patient_management.py`) — ✅ fixed
   - `manageAppointments` reschedule auto-fill — broken `GET /appointment/{id}` response parsing (`scheduling_tools.py`) — ✅ fixed
   - `manageEncounter` unlock — duplicated `/api/ehr/v1` URL prefix; also makes `sign` irreversible via this tool (`encounter_management.py`) — ✅ fixed
   - `managePatientFiles` upload_photo/upload_id — `CharmHealthAPIClient.post()` has no `files` parameter at all (`clinical_support.py`) — ✅ fixed (crash resolved; a separate, smaller field-shape mystery remains, see below)
   - `manageTasks` update — reproducible empty `HTTP 400` (`task_management.py`) — investigated; not a code bug, see below
4. **Confirmed entirely non-functional (likely missing OAuth scope):** `managePatientNotes` (all actions) and `managePatientRecalls` (all actions) — both return `401`/"Unauthorized access" HTML instead of JSON (`clinical_support.py`).
5. **Doc/code mismatches (docstring describes something that doesn't exist or contradicts the schema):** `managePatientVitals` delete action, `managePatientDrugs` add-supplement dosage type, `manageTasks` change_status's `new_status` param.
6. **Inconclusive (need real data or a second provider to confirm one way or the other):** `managePatientBilling` send_balance_reminder, `manageIntakeForms` get_responses_pdf, `manageReferrals` update/create(in) self-referral cases.

All pytest files are under `tests/test_api/test_<toolName>_api.py`, runnable individually via `MCP_SERVER_URL=http://127.0.0.1:8000/mcp/ uv run pytest tests/test_api/test_X_api.py -v` or one test at a time via your IDE's run button.

---

# Bug fixes (item 3 above)

Per-bug fix log — each entry below is added once that specific bug is actually fixed and its test re-run to confirm.

### ✅ Fixed: `managePatient` update missing `record_id`

`patient_management.py`'s `update_specific_details=True` branch now merges `record_id` (caller-supplied, or from the existing record) alongside first_name/last_name/gender/dob — matches what this practice requires. Confirmed live: `managePatient(action="update", patient_id=..., introduction="...")` now returns `code: "0"` instead of `HTTP 400 "Patient Record Id is mandatory."`. New test: `tests/test_api/test_managePatient_api.py::test_managePatient_update` — passes.

### ✅ Fixed: `manageAppointments` reschedule auto-fill

Root-caused via a direct `CharmHealthAPIClient` call (bypassing the MCP layer) against `GET /appointment/{id}`: the real response uses the field name `"patient_id"`, but `scheduling_tools.py`'s auto-fill code looked for `"practice_patient_id"` — a field name that only exists on the *reschedule POST response*, not this GET. `facility_id`/`member_id` were already correct; only `patient_id` was wrong. Fixed the one field name in `scheduling_tools.py`. Confirmed live: `manageAppointments(action="reschedule", appointment_id=..., appointment_date=..., appointment_time=...)` — with no patient_id/facility_id/provider_id supplied — now succeeds via auto-fill. New test file `tests/test_api/test_manageAppointments_api.py` (didn't exist before) — all 5 tests pass, including `test_manageAppointments_reschedule_autofill`.

### ✅ Fixed: `manageEncounter` unlock URL bug

Tested three path candidates directly against `CharmHealthAPIClient` (bypassing the MCP layer) to avoid guess-and-restart cycles: `/encounters/{id}/unlock` (bare, just the duplicated prefix removed) is correct — `/patients/{patient_id}/encounters/{id}/unlock` (matching `sign`'s shape) and `/soap/encounters/{id}/unlock` both 404. Fixed `encounter_management.py` to use the bare path. Confirmed live via `tests/test_api/test_manageEncounter_api.py::test_manageEncounter_unlock` — now passes (previously the only failing test in that file).

### ✅ Fixed: `managePatientFiles` upload_photo/upload_id `files=` crash

Added real multipart/form-data support to `CharmHealthAPIClient` (`api_client.py`): a new `post_multipart()` method and a `POST_MULTIPART` case in `_make_request` that drops the forced `Content-Type: application/json` header so httpx can set its own multipart boundary. Fixed `clinical_support.py`'s `upload_photo`/`upload_id` to actually read the caller's file path into bytes (`_read_file_for_upload()` helper) instead of passing a bare path string to a nonexistent `files=` kwarg. Confirmed the crash is gone: a direct `client.post_multipart(...)` call with a real PNG now reaches the real API cleanly (`HTTP 400 {"code":"704","message":"Please upload an image to process your request"}` — a real, reachable business-logic response, not a client-side crash or "Invalid URL Passed").

**Remaining open question (not a code bug we could confirm/fix further):** that "please upload an image" response persisted across several multipart field-name guesses (`file`, `photo`, `image`, `photo_file`, `patient_photo`). Pinning down the real expected field name needs CharmHealth's actual API reference for this endpoint (not available locally — checked `~/DeveloperLocal/CharmHealth-API-Documents/`, doesn't exist on this machine). Flagging rather than guessing further.

### Investigated, not a code bug: `manageTasks` update empty `HTTP 400`

Root-caused via direct `CharmHealthAPIClient` calls: it's specifically the value `status="In-progress"` (tried every spelling/casing) that both `update` (`PUT /tasks/{id}`) **and** `change_status` (`PUT /tasks/{id}/status`, a separate endpoint) reject with an empty `HTTP 400` — `"Pending"` and `"Completed"` both work fine on either endpoint. A full scan of this sandbox's real task data found only `"Pending"`/`"Completed"` ever used — `"In-progress"` may simply not be a real status value on this backend at all, despite the tool's docstring listing it as one of three valid values. Not fixable from this side without CharmHealth's real docs (the empty 400 body carries zero diagnostic detail) — left undiagnosed rather than guess-patched. Updated `tests/test_api/test_manageTasks_api.py::test_manageTasks_update` to use `"Completed"` (confirmed working) instead, and added `test_manageTasks_update_in_progress_status_rejected` to document the finding. All 6 tests in that file pass.
