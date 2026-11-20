# GenLogin feature matrix / AutumnGenLogin acceptance evidence

**Updated 2026-11-19.** Audited development baseline: v0.5 commit cc74b0cc45a8, plus security PR #5 and scheduler-retry work currently in review. There is no inspected GenLogin/Titan executable for a true same-version runtime comparison.

The [official public release notes](https://genlogin.com/release-notes) currently list GenLogin **4.5.1 (06/08/2026)**. This is a published listing, not a verified installer, license authorization or binary SHA-256.

| Capability | GenLogin reference | AutumnGenLogin development subset | Parity/evidence gap |
|---|---|---|---|
| Profile CRUD, clone, local session | [Profiles](https://docs.genlogin.com/group-profiles/create-profile/overview) | SQLite catalog, persistent data, process locks and opt-in encrypted local session backup/restore (development) | Full UI acceptance, browser portability, migration, large-profile fault injection |
| Groups, tags, bulk management | [Groups](https://docs.genlogin.com/group-profiles/group-profiles) | Basic groups/tags, plus bounded local batch automation across a selected group with safe cancellation | Full GenLogin task scheduler/group assignment equivalence, durable batch history, UI performance, hierarchy |
| Titan/fingerprint rendering | [Technology](https://docs.genlogin.com/) | **Not implemented or verified**. Playwright engines are not Titan | Authorized baseline executable, differential tests, licenses |
| Proxy, locale, WebRTC | [Network](https://docs.genlogin.com/group-profiles/create-profile/network-and-webrtc) | Validated profile settings and proxy options | Real proxy and leak/consistency verification |
| Engine compatibility | [Playwright engines](https://playwright.dev/docs/browsers) | Chromium, Chrome, Edge, Firefox and WebKit launch lanes passed Windows CI | Multi-version compatibility, long-running crashes |
| Extensions | [Extensions](https://docs.genlogin.com/group-profiles/extensions) | Local opt-in Manifest V3 library for bundled Chromium | Marketplace, trust audit, updates/rollback |
| Sequential automation | [Automation](https://genlogin.com/automation) | Typed JSON actions, results and local API | Advanced actions, error recovery, SDK |
| Visual graph automation | [Automation](https://genlogin.com/automation) | Bounded condition/repeat/action graph, Tk editor | Full node catalog, variables, parallel branches, UI usability |
| Recorder | [Automation](https://genlogin.com/automation) | Capture click/select/form selectors with private values redacted | Complex action replay and multi-page tests |
| Scheduler | [Automation](https://genlogin.com/automation) | SQLite one-shot/interval scheduler, manual retry, per-run journal, terminal callback from real BrowserManager, authenticated run history API and GUI | Windows end-to-end, long-running resilience, external-process crash recovery and complete workflow traces; active app required |
| Image click, video, AI, synchronizer, miniapps | [Automation](https://genlogin.com/automation) | **Not implemented** | Complete independent features and tests |
| Full cloud browser-session sync | [Local/cloud profiles](https://docs.genlogin.com/group-profiles/local-and-cloud-profiles) | **Not implemented** | Secure session transfer, conflicts, rollback |
| Optional team metadata sync | [Sharing](https://docs.genlogin.com/group-profiles/share-profile) | Encrypted metadata/workflows, loopback RBAC and revisions; redirect bearer-token fix | Production HTTPS, disaster recovery, wider security tests |
| Public API compatibility | [GenLogin API](https://docs.genlogin.com/genlogin-api/profile-api/1.-profile-list) | Independent authenticated local API | Contract compatibility, versioned SDK |
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
- Batch records are intentionally **in memory only**, retain up to 30 recent batches and do not automatically resume after process restart. Unlike the schedule journal, no workflow values or browser page content are written to disk by this component. Timeouts and late browser completions are marked uncertain, not falsely 'succeeded'.
- Production acceptance still needs resource stress, long-running profile group tests, portable error recovery and a legally grounded GenLogin parity comparison.

## Cancellation regression (2026-11-20, development only)

- SharedBrowserManager.cancel now sets a thread-safe cancel flag **and** schedules cancellation of the currently executing asyncio task on its owning Playwright event loop.
- This interrupts an in-flight selector/navigation wait rather than waiting up to 20 seconds for the Playwright action timeout. A workflow launched on a manually opened browser should cancel without closing that profile.
- The Windows Chromium integration test intentionally waits for a nonexistent selector, requests cancellation and verifies a terminal `cancelled` result within five seconds. This tests manager behavior, not raw Playwright alone.
- Cancellation cannot undo actions already accepted by a website, and it is not a guarantee that all outstanding I/O has stopped before a browser shutdown.
