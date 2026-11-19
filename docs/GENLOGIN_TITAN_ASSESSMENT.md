# GenLogin/Titan feature-parity evidence and release HOLD

Assessed **2026-11-19**. Public-product comparison only. The official GenLogin release-notes page shows **v4.5.1 (06/08/2026)** as its most recent listed release at assessment time: https://genlogin.com/release-notes . This date reflects the public listing, **not** a verified installed binary. We have not been provided its installer, SHA-256, license authorization or a lawful capture of Titan's implementation.

## Source-backed comparison

| Capability | GenLogin published evidence | AutumnGenLogin v0.5 source and checked boundary |
|---|---|---|
| Browser profiles, groups and local sessions | https://docs.genlogin.com/group-profiles/create-profile/overview | Local SQLite, per-profile user-data folders and OS locks; Chromium persistence/independence tested on Windows |
| Shared browser runtime | Public product docs describe multi-profile use, not a documented Playwright architecture | One async Playwright driver and loop, several isolated persistent contexts; tested in Windows Chromium |
| Rendering / fingerprint Titan | https://docs.genlogin.com/group-profiles/create-profile/overview | **Not implemented or verified.** Stock Playwright engines are not Titan |
| Native Chrome/Edge/Firefox/WebKit | https://playwright.dev/docs/browsers | Adapters and capability detection; Chromium/Firefox/WebKit tested on Windows; branded Chrome/Edge test lane pending |
| Proxy, WebRTC, locale, timezone | https://docs.genlogin.com/group-profiles/create-profile/network-and-webrtc | Proxy, timezone and locale settings; **no** comprehensive DNS/WebRTC/fingerprint leakage equivalence evidence |
| Extension management | https://docs.genlogin.com/group-profiles/extensions | Manifest V3 manual import for bundled Chromium only; no marketplace, trust verification or auto updates |
| Visual automation, recorder and task scheduler | https://genlogin.com/automation | Bounded condition/repeat node graph, drag-and-link UI, action recorder, persistent one-shot/interval schedules; subsets verified by Windows tests; **not** a full GenLogin node catalog |
| Synchronizer / click by image / video automation | https://genlogin.com/automation | **Not implemented**. Do not confuse ordinary click selectors with image recognition |
| AI automation and template ecosystem | https://genlogin.com/automation | **Not implemented**; no hosted AI API or vendor templates |
| Cloud profiles and team controls | https://genlogin.com/automation | Optional **self-hosted encrypted metadata/workflow** sync with owner/admin/editor/viewer and revision checks; no browser-session or GenLogin-cloud protocol support |
| Third-party API | https://docs.genlogin.com/genlogin-api/profile-api/1.-profile-list | Independently designed loopback API; no GenLogin API compatibility claim |
| Cloudphone and later product enhancements | https://genlogin.com/release-notes | **Not implemented** |

## Real evidence available, and limits

- Windows CI `44457106840` demonstrated unit/GUI-structure checks, local shared Chromium runtime, graph execution, recorder and manual-close lifecycle, Firefox/WebKit smoke, and existing `.venv` upgrade. Tests are synthetic, use local pages and do not authenticate to real platforms.
- A separate branded Chrome/Edge Windows job has been added to the development PR and must pass before the adapter is considered Windows-verified.
- Self-hosted encrypted hub verifies permission enforcement and revision checking via localhost HTTP/SQLite. It has **not** had a hostile-network audit, production TLS deployment, disaster recovery drill, or external security review.
- There is no GenLogin/Titan binary in the available evidence. **The REA GitHub skill was read but its runtime was not registered and no REA binary inspection was executed.** Consult `docs/TITAN_VERIFICATION_PROTOCOL.md` for the required evidence and authorization.

## Why full parity cannot be certified in this change

Feature names, shared browser versions or similar screenshots do not establish the rendering engine, fingerprint consistency, synchronization semantics, support matrix or licensing equivalence. We lack an authoritative GenLogin binary for identical harmless test scenarios. Furthermore, Sybil labels are judgments made by platforms and can depend on factors beyond the browser. No anti-Sybil guarantee is possible or offered.

**Release decision: do not build or publish a new AutumnGenLogin EXE.** The user requires proven full GenLogin parity, not a partial feature expansion. Preserve developer-source changes and tests, keep `docs/RELEASE_GATES.md` truthful, and do not merge uncertain external reverse-engineered code.
