# charm-mcp-server: production API access gaps (CH-907 follow-up)

**For: CharmHealth API/platform team**
**From: Sumana Ramanathan, agent/Studio build track**
**Context:** While probing every charm-mcp-server tool end-to-end against a real production
account (after previously validating the same suite against sandbox), several tools failed in
ways that trace back to this production integration's OAuth token/app registration, not to our
client code. Each finding below was verified directly against `charm-charmehr`'s own
`webapps/api/WEB-INF/security-api-*.xml` — the file/line is cited so it's fast to confirm.

This is **not** a single "grant us everything" ask — the findings split into a few different
categories, listed in the order we'd like them addressed.

---

## 1. Missing OAuth scopes — please grant these to our production app registration

### `patient.quicknotes` — blocks `managePatientNotes` entirely (all 4 actions)

Every quicknotes endpoint requires this scope:

```
security-api-patients.xml:533  GET    /api/ehr/v1/patients/{id}/quicknotes           oauthscope="patient.quicknotes"
security-api-patients.xml:539  POST   /api/ehr/v1/patients/{id}/quicknotes           oauthscope="patient.quicknotes"
security-api-patients.xml:543  PUT    /api/ehr/v1/patients/quicknotes/{id}           oauthscope="patient.quicknotes"
security-api-patients.xml:547  DELETE /api/ehr/v1/patients/quicknotes/{id}           oauthscope="patient.quicknotes"
```

**Observed:** every call gets `HTTP 401` with CharmHealth's own "Unauthorized access" HTML login
page instead of a JSON response — identical in both sandbox and production, so this has never
worked for this integration.

**Ask:** grant `patient.quicknotes` to our production (and sandbox) app registration.

### `patient.referral` — blocks `manageReferrals` entirely (create/list/get/update/respond)

Every referral endpoint (20 of them, in and out direction) consistently requires this one scope:

```
security-api-referral.xml:4   POST /api/ehr/v1/referrals/out              oauthscope="patient.referral"
security-api-referral.xml:16  GET  /api/ehr/v1/referrals/out               oauthscope="patient.referral"
security-api-referral.xml:27  GET  /api/ehr/v1/referrals/out/{id}          oauthscope="patient.referral"
security-api-referral.xml:58  PUT  /api/ehr/v1/referrals/out/{id}          oauthscope="patient.referral"
security-api-referral.xml:109 POST /api/ehr/v1/referrals/in                oauthscope="patient.referral"
... (every other /referrals/* endpoint, same scope, no exceptions)
```

**Observed:** `HTTP 401` "Unauthorized access" HTML on every call — but only in **production**.
The identical calls all pass cleanly in sandbox, so `patient.referral` is granted there but not
here. This is the inverse of the quicknotes finding — a production-only gap.

**Ask:** grant `patient.referral` to our production app registration (already present in sandbox).

---

## 2. Backend misconfiguration — likely a copy-paste bug in your security config, not a grant request

### `POST /patients/{id}/recalls` (the "add" action) is declared under the wrong scope

Every other recall endpoint uses `patient.recall`, but `add` alone uses `patient.chartnote`:

```
security-api-patients.xml:198  GET    /api/ehr/v1/patients/{id}/recalls              oauthscope="patient.recall"
security-api-patients.xml:204  GET    /api/ehr/v1/patients/{id}/recalls/{id}         oauthscope="patient.recall"
security-api-patients.xml:206  POST   /api/ehr/v1/patients/{id}/recalls              oauthscope="patient.chartnote"  <-- mismatch
security-api-patients.xml:209  PUT    /api/ehr/v1/patients/{id}/recalls/{id}         oauthscope="patient.recall"
security-api-patients.xml:212  PUT    /api/ehr/v1/patients/{id}/recalls/{id}/markcomplete  oauthscope="patient.recall"
security-api-patients.xml:215  DELETE /api/ehr/v1/patients/{id}/recalls/{id}         oauthscope="patient.recall"
```

**Observed:** in production, `list`/`update`/`delete` all authenticate fine (`patient.recall` is
granted), but `add` fails with a generic `HTTP 400 {"code":"6","message":"Internal Error"}` — a
JSON response, not a 401, consistent with the request reaching business logic under a *different*
scope (`patient.chartnote`, which is broadly granted since chart-note/encounter tools work fine
everywhere else) rather than being stopped at the auth gate. Same failure in sandbox.

**Ask:** this doesn't need a new scope grant — please check whether `POST /patients/{id}/recalls`
is *intended* to require `patient.chartnote` instead of `patient.recall`. If not, it looks like a
copy-paste error in `security-api-patients.xml:206` that should be `oauthscope="patient.recall"`
to match its siblings.

---

## 3. Not scope issues — flagging so these don't get bundled into the scope-grant work

### `manageMessages` WhatsApp send — wrong endpoint on our side, and the real one may not be OAuth-exposed

Our code (`communication.py`) currently calls `POST /messages/whatsapp/patient/{id}/send`, which
**does not exist anywhere in your security config** — that's why it 404s with
`{"code":5,"message":"Invalid URL Passed"}` in both sandbox and production. The real endpoint
appears to be:

```
security-api-settings.xml:450  POST /api/ehr/v1/messages/whatsapp/send_free_form_messages
                                  params: pat_id, number, from_pat, content
```

Notably, **this endpoint (and its neighbors — `send_opt_in`, `force_opt_out`,
`map_unmapped_messages`) declare no `oauthscope` attribute at all**, unlike every properly
partner-exposed endpoint elsewhere in your config. It also lives in `security-api-settings.xml`
rather than alongside the other `user.message`-scoped messaging endpoints.

**Ask (question, not a grant request):** is `send_free_form_messages` meant to be reachable via
partner OAuth tokens at all? If yes, could it get an `oauthscope` (presumably `user.message`, to
match the rest of messaging) so we can fix our path and actually use it? We'll fix our client code
to call the correct path/param shape once this is confirmed either way.

### `managePatientRecalls` delete — real bug, but not an auth bug

`DELETE /patients/{id}/recalls/{id}` uses the same `patient.recall` scope as `list` (which we've
confirmed is granted and working in production). When we ran this with a placeholder/nonexistent
`record_id`, it returned `HTTP 500 {"code":"1000","message":"Internal Error"}` instead of a clean
404. Flagging as a minor robustness gap (unhandled exception on a nonexistent ID) — not something
scope-related, and not blocking for us since we can't produce a real recall to delete until item 2
above is resolved anyway.

### `manageMessages` SMS — not broken, no action needed

`POST /textmessages/patient/{id}/outgoing` (`oauthscope="user.message"`) works correctly in
production. It's correctly *rejected* in sandbox ("Bidirectional sms is not enabled") — that's a
per-practice feature toggle, not a scope or code issue. Mentioning only so it's not mistaken for
part of the same pattern as the items above.

### `manageTasks` update with `status="In-progress"` — not reproducible in production

All task endpoints consistently use `oauthscope="user.task"`, and the request schema
(`security-api-members.xml:404-415`) explicitly allows `status` to be one of
`Pending|In-progress|Completed`. This value is rejected with an empty `HTTP 400` in sandbox only;
production accepts it cleanly. Looks like a sandbox-account-specific anomaly, not a real
restriction — no action needed from the platform team, just flagging for completeness.

---

## Summary — what we're actually asking for

| # | Scope/endpoint | Ask |
|---|---|---|
| 1 | `patient.quicknotes` | Grant to production app registration |
| 2 | `patient.referral` | Grant to production app registration (already present in sandbox) |
| 3 | `POST /patients/{id}/recalls` (`oauthscope="patient.chartnote"`) | Confirm intended scope; likely fix to `patient.recall` |
| 4 | `POST /messages/whatsapp/send_free_form_messages` (no `oauthscope`) | Confirm whether OAuth-exposed; if so, assign a scope so we can fix our path |

Items 5–7 (recalls delete 500, SMS, tasks in-progress) require no platform action — included only
for completeness/context.

Full raw test evidence backing every finding above: [`api_probe_results_production.md`](api_probe_results_production.md)
and [`api_probe_results_sandbox.md`](api_probe_results_sandbox.md) in this repo.
