# Strict feature-parity release gates

Decision: **HOLD EXE BUILD**. User requested no Windows release build until functional equivalence with GenLogin has been *verified*, not merely asserted.

Assessment baseline: 2026-11-18; engineering audit follow-up: 2026-11-19. Source fixes are not evidence of GenLogin parity. See `FEATURE_MATRIX.md` and `GENLOGIN_TITAN_ASSESSMENT.md`. This checklist is deliberately not marked complete by passing unit tests or by matching promotional features.

## Gate A: complete, independently sourced feature inventory

- [ ] Pin exact GenLogin release, edition, plan and install binary with SHA-256, date, provenance, and license review.
- [ ] Capture and witness GenLogin user-visible flows with *synthetic* accounts, no real login data and no protected code copying.
- [ ] Confirm a feature matrix on Windows across: profiles, proxies, extensions, automation UI/recorder, scheduling, API, export, cloud/team and safe error handling.
- [ ] Obtain legal authorization for any binary inspection and retain REA Evidence IDs and independent observations. **Reading REA skill is not execution of REA**.

## Gate B: implementation

- [x] Local SQLite catalog, validated profile settings, groups, tags, metadata import/export.
- [x] Separate Chromium user-data dirs, cross-process locks, simple per-profile proxy.
- [x] Credentials stored via OS vault rather than profile metadata.
- [x] Strict non-code JSON browser actions, API protected with random bearer token and loopback bind.
- [x] Visual sequential step builder (drag reorder, edit, duplicate, import/export). Not graph/recorder parity.
- [x] Manual Manifest V3 extension import, opt-in attach per Chromium profile, permission preview, ZIP traversal protection. Not Chrome Web Store parity.
- [ ] Production-grade extensions: independent auditing/signatures, updates, rollback, package version migration, permission prompts for changes.
- [ ] Complete GenLogin-equivalent visual graph engine (branches, loops, variables, replay, execution traces), element recorder, scheduler, template ecosystem.
- [ ] Chrome/Firefox engine compatibility and verified device/OS/WebRTC consistency without breaking websites or violating terms.
- [ ] Encryption-backed **optional** cloud sync, conflict handling, access control, recovery and team RBAC.
- [ ] Public API compatibility/SDK, documented stable surface, external integrations.
- [ ] GUI accessibility, localization, failure recovery, unsaved edits, performance testing for large catalogs.
- [ ] Feature behavior comparisons against a legally inspected exact GenLogin release.

## Gate C: security and legal review

- [ ] Confirm browser binary licensing and distribution, third-party attribution and SBOM for all packaged components.
- [ ] Verify extension and profile-data read/write failures do not leak credentials, cookies, or API token to logs and exports.
- [ ] Threat-model the loopback API, extension execution, backup restore, migration and malicious archives.
- [ ] Validate browser update/recovery with no silent data loss and no hidden remote telemetry.
- [ ] Never claim Titan or Sybil-detection immunity. Do not implement mechanisms specifically to subvert platform anti-fraud or identity rules.

## Gate D: real test execution

- [ ] Tests for every feature, including negative paths and data migration.
- [x] Windows headless Chromium profile isolation and persistence test passed on development commit `08e2516ea7d4` (CI `44235696630`).
- [ ] Windows headed actual Chrome, Edge and bundled Chromium tests on a fresh VM.
- [x] Windows headless Playwright Chromium loaded a benign local MV3 extension and observed the service worker (CI `44235696630`). This does not validate arbitrary extensions.
- [x] Windows Tkinter structural smoke for profile, extension and workflow tab instantiation (CI `44235696630`).
- [ ] Full GUI interaction smoke, screenshots, keyboard/a11y and usability acceptance.
- [ ] Concurrency, storage corruption, disk-full, emergency shutdown, proxy failure and application reinstall. **Some** mocked close/corruption/rollback regressions added 2026-11-19; production Windows fault injection pending.

## Release decision

Only after all necessary gates are demonstrated can CI be changed to produce a Windows EXE. The GitHub Actions workflow currently **does not** build binaries. Existing older EXEs are historical development builds, not a validated parity release.

### 2026-11-19 follow-up

[ ] Validate Windows existing `.venv` upgrade (`tzdata`), corruption dialog, staging cleanup after a restart, API storage error and sensitive-memory expiry through the current CI run. These regressions have been added to source and CI; mark verified only after their executed Windows run succeeds. This does not reopen the EXE build gate.

### v0.5-dev code milestones (NOT a parity release)

- [x] Source implementation of bounded condition/repeat graph, graphical editor, safe click/selector recorder, durable local scheduling.
- [x] Source implementation of an encrypted, self-hosted **metadata-only** sync service and server-side team RBAC. Full automatic session sync remains **not implemented**.
- [x] Source implementation of one shared async Playwright driver and optional per-thread SQLite connections, plus Chromium/Chrome/Edge/Firefox/WebKit adapters.
- [ ] Run and preserve **complete** Windows CI proof for all new features, including headed Tk graph editor, cloud conflicts under concurrency, long-running schedules, browser crash recovery and Chrome/Edge. Partial evidence: Windows CI `44457650505` passed 5/5 jobs (unit/GUI structure, Chromium shared driver + recorder/graph, Firefox/WebKit smoke, branded Chrome/Edge smoke and venv upgrade). These tests do **not** establish all features or Titan parity.
- [ ] Browser performance, GUI accessibility and production incident recovery validation.
- [ ] Direct, legally authorized comparison with pinned GenLogin/Titan binary. This evidence is not available, so the release HOLD remains.

See `FEATURES_050.md`, `TEAM_SYNC_OPERATIONS.md`, and `TITAN_VERIFICATION_PROTOCOL.md` for precise limitations.

## 2026-11-22 reproducible Windows Batch SQLite cleanup gate

Windows main CI run `45004558299` encountered a `WinError 32` in
`test_batch.BatchTests.test_redacts_workflow_values_and_does_not_keep_payload`:
the batch *result* was already terminal, but a background batch worker had
not yet left its `finally` block and closed its thread-owned SQLite
connection when `TemporaryDirectory.cleanup()` started.

The tests must now call the existing `BatchRunner.wait(batch_id)`
thread-join/cleanup barrier **before** deleting their Windows test databases.
This is applied consistently to synthetic Batch tests, the local API Batch
test teardown and real Chromium batch integration; no arbitrary sleep,
exception swallowing or loose file-handle retry is an acceptable substitute.
A terminal automation outcome alone does not prove its worker resources
have been released. Regression must pass in a new Windows PR run and on
`main` after merge. **This remains a quality fix, not full feature parity
or permission to create EXE artifacts.**

## 2026-11-23 local QA synchronization expansion (not parity)

- Test-only live synchronizer now targets specially marked buttons across
  matching tab ordinals and same-origin synthetic iframes on literal
  `http://127.0.0.1:port`. It refuses external iframe URLs, unmatched tab
  counts, missing/ambiguous iframe targets and busy follower sessions.
- Status differentiates the number of **master gestures** from individual
  **follower deliveries** and failures. The existing 50-gesture safety cap
  cannot be exhausted five times faster merely by having five followers.
- Explicitly **not** implemented: arbitrary-site live synchronization, form
  contents, credentials, navigation, scroll, keyboard, cookies, session
  replication or a GenLogin/Titan-equivalent workflow. Those require separate
  threat modeling, consent, requirements and runtime acceptance.

## 2026-11-23 async profile lease ownership (development)

- Browser startup now owns each OS-backed profile lock in a dedicated worker
  thread for the profile's lifetime. Both acquisition and release run on the
  **same worker**, including Windows `msvcrt.locking`. The Playwright event
  loop awaits an asynchronous completion signal instead of filesystem I/O.
- A cancellation during delayed acquisition signals release even if the
  worker acquires the lock after the coroutine has been cancelled; a completed
  normal release awaits worker termination before reporting profile stopped.
- Tests exercise OS lock exclusivity, shared-loop heartbeat while acquisition
  stalls, and cancellation while a synthetic acquire remains in progress.
  A real Windows Chromium integration lane still checks profile data-dir
  closure and filesystem cleanup. Deliberate crash/power-loss recovery and
  prolonged multi-process lease contention are not fully accepted.
