# GenLogin feature matrix / AutumnGenLogin acceptance evidence

**Updated 2026-11-19.** Audited development baseline: v0.5 commit cc74b0cc45a8, plus security PR #5 and scheduler-retry work currently in review. There is no inspected GenLogin/Titan executable for a true same-version runtime comparison.

The [official public release notes](https://genlogin.com/release-notes) currently list GenLogin **4.5.1 (06/08/2026)**. This is a published listing, not a verified installer, license authorization or binary SHA-256.

| Capability | GenLogin reference | AutumnGenLogin development subset | Parity/evidence gap |
|---|---|---|---|
| Profile CRUD, clone, local session | [Profiles](https://docs.genlogin.com/group-profiles/create-profile/overview) | SQLite catalog, persistent data, process locks and opt-in encrypted local session backup/restore (development) | Full UI acceptance, browser portability, migration, large-profile fault injection |
| Groups, tags, bulk management | [Groups](https://docs.genlogin.com/group-profiles/group-profiles) | Groups/tags, bounded batch automation and SQLite history of per-profile terminal outcomes with crash-safe uncertainty (development) | Complete GenLogin task workflow parity, long-run reliability, UI performance, hierarchy |
| Titan/fingerprint rendering | [Technology](https://docs.genlogin.com/) | **Not implemented or verified**. Playwright engines are not Titan | Authorized baseline executable, differential tests, licenses |
| Proxy, locale, WebRTC | [Network](https://docs.genlogin.com/group-profiles/create-profile/network-and-webrtc) | Validated profile settings and proxy options | Real proxy and leak/consistency verification |
| Engine compatibility | [Playwright engines](https://playwright.dev/docs/browsers) | Chromium, Chrome, Edge, Firefox and WebKit launch lanes passed Windows CI | Multi-version compatibility, long-running crashes |
| Extensions | [Extensions](https://docs.genlogin.com/group-profiles/extensions) | Local MV3 import plus confirmed offline version updates/rollback on stopped profiles (development) | Verified publisher signatures, marketplace, auto-updates, extension API compatibility |
| Sequential automation | [Automation](https://genlogin.com/automation) | Typed JSON actions, results and local API | Advanced actions, error recovery, SDK |
| Visual graph automation | [Automation](https://genlogin.com/automation) | Bounded action/condition/repeat plus ephemeral literal and captured-text variables, Tk graph editor | Full GenLogin node catalog, parallel branches, advanced retries, GUI usability |
| Recorder | [Automation](https://genlogin.com/automation) | Capture click/select/form selectors with private values redacted | Complex action replay and multi-page tests |
| Scheduler | [Automation](https://genlogin.com/automation) | SQLite one-shot/interval scheduler, manual retry, per-run journal, terminal callback from real BrowserManager, authenticated run history API and GUI | Windows end-to-end, long-running resilience, external-process crash recovery and complete workflow traces; active app required |
| Image click, video, AI, synchronizer, miniapps | [Automation](https://genlogin.com/automation) | **Not implemented** | Complete independent features and tests |
| Full cloud browser-session sync | [Local/cloud profiles](https://docs.genlogin.com/group-profiles/local-and-cloud-profiles) | **Not implemented** | Secure session transfer, conflicts, rollback |
| Optional team metadata sync | [Sharing](https://docs.genlogin.com/group-profiles/share-profile) | Encrypted metadata/workflows, loopback RBAC and revisions; redirect bearer-token fix | Production HTTPS, disaster recovery, wider security tests |
| Public API compatibility | [GenLogin API](https://docs.genlogin.com/genlogin-api/profile-api/1.-profile-list) | Authenticated, native /v1 loopback API and no-redirect Python SDK (development) | GenLogin protocol parity, stable contract versioning, external integration acceptance |
| Release, license and reliability | Engineering acceptance | Test-only Windows CI, diagnostics, staged deletion | Full GUI acceptance, fault injection, license/SBOM, signing |

## Verification boundaries

- Windows CI 44458151452: five jobs passed on v0.5 main, covering separate unit, Chromium, Firefox/WebKit, Chrome/Edge and old-venv-upgrade lanes. Unit tests skipped due to missing browser binaries do not count as executed real-browser checks.
- Security CI 44542164849: five jobs passed, including the cloud-client redirect regression. This does not certify production cloud security.
- Scheduler-retry work is **not** accepted until its own CI and merge pass. Submission to BrowserManager is not proof of workflow completion.
- Public GenLogin marketing/documentation describes scope, not specific installed binary behavior. Native Titan parity remains unverified.

**Release status: HOLD EXE BUILD.** See RELEASE_GATES.md and TITAN_VERIFICATION_PROTOCOL.md. Do not publish an EXE simply because unit tests are green.

## Scheduled run journal development note (not release acceptance)

- A separate SQLite `schedule_runs` table holds dispatch UUID, profile/job IDs, timestamps, terminal state and **exception class only**. It never intentionally writes extracted text, screenshots, workflow payloads, cookies or raw error messages.
- Claims and journal entries are created atomically. A `dispatch_pending` record after a crash is **uncertain**, not proof the action never started; never replay automatically.
- BrowserManager callback updates `succeeded`, `failed` or `cancelled` after the workflow ends, rather than inferring completion from the scheduler callback's return.
- Completion can race with `submitted` acknowledgement; the journal never downgrades a terminal result. For overlapping interval runs, only the newest dispatch may update a schedule's overall status.
- The GUI Scheduler tab shows recent executions. Opt-in local API GET `/v1/schedules/history?limit=50` is bearer-token protected; optional `schedule_id` filters a job; limit is 1-200.
- Deleting a profile or a schedule removes its journal entries. Old v0.5 SQLite profile data remains valid, and the new table is created without altering the profile schema.
- A Windows Chromium end-to-end test is required for acceptance of actual completion. This is an incremental architecture improvement, not GenLogin/Titan parity.

## 2026-11-20 bounded batch feature

- Uses one strict, already validated local JSON/graph workflow on up to 200 explicitly selected profile UUIDs. A dedicated `Batch tasks` tab requires choosing one specific group and confirming the number of profiles. The backend caps parallel attempts at six.
- Profiles remain independent persistent contexts. Unlike a native synchronizer, browser actions are **not mirrored live** between profiles.
- Each batch reports queued/submitting/running/succeeded/failed/cancelled/uncertain per-profile states and safely redacted exception types. Cancellation requests only affect runs whose UUID matches that batch's accepted BrowserManager run; queued profiles are never launched after cancellation.
- The batch API is **disabled by default** along with the local API. On opt-in, bearer-authenticated endpoints include POST `/v1/batches`, GET `/v1/batches`, GET `/v1/batches/{uuid}` and POST `/v1/batches/{uuid}/cancel`.
- Batch records persist to a new `batch_history` SQLite table. A bounded 30-batch in-memory working set remains, with up to 100 completed history records retained. Only IDs, timestamps, statuses and safe exception type names are stored; workflow payloads, extracted text and cookies are never written to the journal. Batch execution still requires the application to remain open. No automatic replay occurs after restart.
- Production acceptance still needs resource stress, long-running profile group tests, portable error recovery and a legally grounded GenLogin parity comparison.

## Cancellation regression (2026-11-20, development only)

- SharedBrowserManager.cancel now sets a thread-safe cancel flag **and** schedules cancellation of the currently executing asyncio task on its owning Playwright event loop.
- This interrupts an in-flight selector/navigation wait rather than waiting up to 20 seconds for the Playwright action timeout. A workflow launched on a manually opened browser should cancel without closing that profile.
- The Windows Chromium integration test intentionally waits for a nonexistent selector, requests cancellation and verifies a terminal `cancelled` result within five seconds. This tests manager behavior, not raw Playwright alone.
- Cancellation cannot undo actions already accepted by a website, and it is not a guarantee that all outstanding I/O has stopped before a browser shutdown.

## 2026-11-20 offline extension updates

- A candidate Manifest V3 ZIP is imported but remains disabled until the user explicitly reviews its full new API and host permissions and confirms migration.
- Updates only connect packages with exactly matching extension names and differing version strings. **Names do not authenticate publisher identity** and no signature validation is claimed.
- Attached profiles must be closed; per-profile OS leases prevent updates/rollback while a Chromium instance has the profile open. Previous package contents are immutable and retained.
- The SQLite upgrade record includes old/new immutable package UUIDs and affected profile UUIDs. Rollback is an explicit user action that refuses ambiguous association changes instead of guessing.
- No Chrome Web Store integration, unattended download or automatic update is implemented. Source trust, permissions, compatibility and privacy require independent verification before production release.

## 2026-11-20 opt-in local API SDK

- Python stdlib client `autumn_genlogin.client.AutumnAPIClient` only accepts literal IPv4/IPv6 loopback HTTP URLs, bypasses environment HTTP proxies and refuses redirects to avoid bearer token forwarding.
- Supports profile list/open/stop, graph/steps automation, recorder, latest execution, schedule history and bounded group batch operations. The SDK does **not** expose source-code execution or unauthorized external requests.
- API error responses now map browser busy/resource conflicts to a sanitized HTTP 409, rather than disconnecting the client. The client has typed errors and no token in repr.
- The native API is independent and **not** compatible with the GenLogin proprietary API. Formal OpenAPI contract certification, migration compatibility, complete SDK coverage, stress and a hostile local process threat model remain outstanding.

## 2026-11-20 durable batch completion journal (development)

- A write-ahead record is saved **before** each profile's asynchronous browser dispatch. This preserves the distinction between queued (known not submitted) and submitting/running (possibly acted on a website).
- An OS-backed per-batch lease remains held while a live worker pool exists. On a later read, another app instance does not overwrite a live batch it cannot lock. After an unclean shutdown, only a batch whose lease can be acquired is recovered: formerly submitting/running records become `uncertain`, queued records `cancelled`, and the batch is marked `partial` or `cancelled`. No workflow content is stored or replayed.
- Recovering history does not prove what a website actually processed before a crash. Users must manually inspect external effects before considering any rerun.
- Completing a batch releases its lease only after the terminal snapshot was successfully persisted. Missing database writes fail closed. SQLite connections owned by batch threads are closed when each worker exits.
- Active batches block deletion of their referenced profile, even if that profile has not launched yet. Deleting a profile linked to a terminal batch removes the **whole** batch history record, preventing orphaned references to deleted profiles.
- This is not a transactional exactly-once guarantee for web actions, not durable scheduling of queued batch work and not GenLogin/Titan parity. Real Chromium Windows CI still needs to validate saved successful completion on each change.

## 2026-11-20 local workflow variable nodes (development)

- `set_variable` with `name` and literal `value` and `capture_text` with `name` and Playwright `selector` are explicit graph nodes. The graph designer can create/edit them. Up to 32 distinct ASCII-name variables and 4,096 characters per value are allowed. At most 500 graph node operations per execution, with repeat cap unchanged.
- Action string fields can interpolate exactly `{{name}}` with no arbitrary expression evaluation. Actions are revalidated **after** interpolation. Missing variables, noncanonical placeholders, invalid URLs and expanded values above limits cause the workflow to fail rather than silently proceeding.
- Captured page text is **tainted** and may populate later page actions (e.g. a form field) but may not be inserted into a `goto` URL, preventing accidental URL-based page-data exfiltration. Literal variables can supply navigation components.
- Variables live only inside the asynchronous execution frame; neither terminal run result, SQLite batch/scheduler history nor activity log receives values. Capture uses real Playwright `inner_text` with a bounded locator timeout.
- This development subset does not add a general-purpose scripting language, database bindings, flow-wide persistent variables, arbitrary network requests, or GenLogin/Titan compatibility.
