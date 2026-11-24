# Roadmap (release held pending verified feature parity)

## Current development implementation

- Local profile CRUD, clone, groups/tags, proxy settings, credential vault, metadata import/export, process locks.
- Standard Chrome/Edge/Chromium persistent contexts via Playwright. Manual local Manifest V3 extension packages for bundled Chromium only.
- Strict sequential JSON automation and an accessible basic visual step editor; token-authenticated loopback control API.
- Tests for SQLite, API, locks, validation, extension upload security and visual-step definitions; real-browser CI integration test separated from unit tests.
- Windows Actions now tests without packaging a release binary.

## Work before release

1. Audit actual GenLogin/Titan binaries only when legal rights, version and instrumentation are provided. Create witnessed behavior/evidence matrix.
2. Complete profile management: editable view columns, sorting, secure import/export policy, safe profile backups and migrations, proxy tester, browser version manager.
3. Implement extension permission change review, updates, rollback and actual cross-version compatibility tests.
4. Implement a graph-based workflow engine, recorder, variables, loops, branches, task scheduler, structured results and controlled execution.
5. Implement team/cloud only with explicit opt-in and a separately audited authenticated backend and encryption.
6. Pass real Windows GUI tests, Chromium/Chrome/Edge e2e tests, failure injection, license review, packaging SBOM and acceptance criteria.
7. Only then reintroduce the Windows EXE build workflow with approvals and reproducibility attestations.

See `RELEASE_GATES.md` for the actual acceptance contract.


## 2026-11-23 incremental Tk module extraction

- The Scheduler pane and its dispatch callback live in
  `autumn_genlogin/schedule_tab.py` as `ScheduleTabMixin`. The main
  `App` continues to own Tk widgets, browser manager and its
  `_run_ui_task` worker/completion queue. Existing public callback names
  and scheduler transactional behavior are preserved.
- This first extraction removes approximately 130 inline source lines
  from `ui.py` without moving Tk calls onto background threads.
  Dedicated architecture tests assert the inheritance contract and absence
  of blocking `.result()` waits in the extracted module. Windows GUI
  acceptance and regression suites must pass after refactor.
- Remaining large tabs (Profiles, Batch, Miniapps, Cloud, Backup) **have
  not been extracted yet**. Decomposing the class must proceed in bounded,
  independently tested steps, not as an unreviewed multi-thousand-line
  reorganization. No functional parity or EXE release follows from refactor.


## 2026-11-23 Batch tab module and I/O isolation (development)

- `autumn_genlogin/batch_tab.py` now holds the Batch pane in
  `BatchTabMixin`, composed into `App` beside `ScheduleTabMixin`.
  Dialogs/consent, tab state and all widgets remain Tk-main-thread only.
- Batch start, cancellation, history retrieval and selected-batch details
  run through `_run_ui_task` background workers. Bounded history refreshes
  discard older out-of-order replies and preserve still-existing selection.
  This avoids freezing Tk on batch journal SQLite or live per-batch OS lease
  checks during crash recovery.
- Synthetic Win32/Tk heartbeat regression deliberately blocks journal
  listing while the GUI continues pumping callbacks. Full long-lived GUI
  stress and independent vendor parity remain outstanding. Profiles,
  Miniapps, Cloud, Backup and other sections still require careful,
  separately tested extraction.

## 2026-11-24 Cloud tab extraction

CloudTabMixin now owns the Team Hub panel, metadata review, and manual encrypted
archive handoff callbacks. The same App worker bridge and consent prompts are
retained; this is a behavior-preserving extraction, not automatic session sync.
Existing Windows GUI tests remain the acceptance gate. Other tabs still need
separate extraction and review.
