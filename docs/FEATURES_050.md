# AutumnGenLogin 0.5-dev: implemented capabilities and known gaps

**Status:** development code. No EXE or GenLogin parity claim. All percentages and feature completion claims require executed platform test evidence. Current source baseline is based on repository commit `787095531ac0`.

## Delivered in the 0.5-dev source

| Subsystem | Implementation | Verification limits |
|---|---|---|
| Node graph | `graph.py` strict schema (`start`, `action`, `condition`, `repeat`, `end`), labelled transitions, bounded loops (20/loop and 500 operations/run), `GraphEditor` draggable native Tk canvas and importer/exporter | Unit tests; Windows interactive usability and edge cases still need acceptance |
| Recording | Browser-owned click, select, check, uncheck and fill-selector capture; input and selected option values redacted; disabled unless requested; opt-in import into visual builder | Real Windows Chromium recorder/last-page-close test passed CI `44457106840`. Not full GenLogin recorder parity |
| Local schedules | `scheduler.py`: durable local UTC next-run, one-shot/interval, atomic claiming across processes and skip missed runs | Unit tests; UI/Windows long-duration tests needed. Scheduler only runs while desktop app is open |
| Team hub | `team_sync.py`: opt-in self-hosted loopback server, token login, owner/admin/editor/viewer roles, optimistic revision conflict checks | Localhost HTTP/SQLite integration tests. No hosted public service or enterprise compliance |
| Encrypted sync | Client-side AES-GCM encryption with scrypt-derived key and fresh salt/nonce. Only allowlisted profile metadata and workflow data; explicit push/pull and import confirmation | **Does not** sync cookies, browser session folders, proxy settings, passwords, extension binaries. Passphrase exchange/backup up to user |
| Engine adapters | Playwright persistent contexts for Chromium, Chrome, Edge, Firefox, WebKit; capability checks for extension loading | Windows Firefox/WebKit smoke passed CI `44457106840`; Chrome/Edge native launch still unverified. **Not** Titan Browser engine |
| Shared driver | `SharedBrowserManager`: one async Playwright driver/event loop thread, up to six distinct browser contexts, per-profile OS leases, managed lifecycle, recorded actions, cancellation | Windows Chromium integration passed CI `44457106840`, including manual last-page close. Long-running crash/fault injection untested |
| SQLite pool | Optional `Store(reuse_connections=True)`: per-thread connection cache, explicit close on main GUI and scheduler worker exit, WAL and foreign keys | Unit tests; performance/Windows disk lock benchmarks pending |

## Remaining GenLogin parity blockers

- No Titan binary (SHA-256, version, license and legitimate inspection authorization) was provided; REA source/skill is not a replacement. **No authorized comparative reverse engineering has occurred.**
- No custom Titan-equivalent rendering core, WebRTC/network fingerprint equivalence proof, or credible immunity from Sybil/account linking. Standard context emulation is not a stealth engine.
- No session-folder cloud sync (excluded intentionally due to high privacy and concurrency risk), GenLogin proprietary cloud protocol, or full team live collaboration.
- No complete GenLogin automation node catalog: parallel branches, scripting, frames, native keyboard/mouse sync, conditional data transformations, market templates and API compatibility are not implemented.
- No automatic remote sync; currently explicit push/pull with revision conflict and user confirmation.
- Firefox/WebKit require browser binaries (`python -m playwright install firefox webkit`); unpacked Chrome extensions work only with supported Playwright Chromium.
- No installer/signing, managed browser updates, extension marketplace/signature audit, complete accessibility/localization and production support.

## Correct release decision

The release hold is unchanged: GitHub Actions has **test jobs only**; `BUILD-EXE-WINDOWS.cmd` remains blocked. Passing tests is evidence for a subset of behaviors, not parity with GenLogin.
