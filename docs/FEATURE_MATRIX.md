# GenLogin feature matrix / AutumnGenLogin acceptance evidence

**Updated 2026-11-19.** Audited development baseline: v0.5 commit cc74b0cc45a8, plus security PR #5 and scheduler-retry work currently in review. There is no inspected GenLogin/Titan executable for a true same-version runtime comparison.

The [official public release notes](https://genlogin.com/release-notes) currently list GenLogin **4.5.1 (06/08/2026)**. This is a published listing, not a verified installer, license authorization or binary SHA-256.

| Capability | GenLogin reference | AutumnGenLogin development subset | Parity/evidence gap |
|---|---|---|---|
| Profile CRUD, clone, local session | [Profiles](https://docs.genlogin.com/group-profiles/create-profile/overview) | SQLite catalog, persistent user data, cross-process locks, Windows Chromium tests | GUI end-to-end, migration and failure injection |
| Groups, tags, bulk management | [Groups](https://docs.genlogin.com/group-profiles/group-profiles) | Basic groups/tags and local profile list | Bulk workflow launch, UI performance, hierarchy |
| Titan/fingerprint rendering | [Technology](https://docs.genlogin.com/) | **Not implemented or verified**. Playwright engines are not Titan | Authorized baseline executable, differential tests, licenses |
| Proxy, locale, WebRTC | [Network](https://docs.genlogin.com/group-profiles/create-profile/network-and-webrtc) | Validated profile settings and proxy options | Real proxy and leak/consistency verification |
| Engine compatibility | [Playwright engines](https://playwright.dev/docs/browsers) | Chromium, Chrome, Edge, Firefox and WebKit launch lanes passed Windows CI | Multi-version compatibility, long-running crashes |
| Extensions | [Extensions](https://docs.genlogin.com/group-profiles/extensions) | Local opt-in Manifest V3 library for bundled Chromium | Marketplace, trust audit, updates/rollback |
| Sequential automation | [Automation](https://genlogin.com/automation) | Typed JSON actions, results and local API | Advanced actions, error recovery, SDK |
| Visual graph automation | [Automation](https://genlogin.com/automation) | Bounded condition/repeat/action graph, Tk editor | Full node catalog, variables, parallel branches, UI usability |
| Recorder | [Automation](https://genlogin.com/automation) | Capture click/select/form selectors with private values redacted | Complex action replay and multi-page tests |
| Scheduler | [Automation](https://genlogin.com/automation) | Durable SQLite one-shot and interval dispatch while app is open; manual retry under development | Execution completion, crash recovery and durable run history |
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
