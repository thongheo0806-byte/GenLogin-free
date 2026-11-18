# Strict feature-parity release gates

Decision: **HOLD EXE BUILD**. User requested no Windows release build until functional equivalence with GenLogin has been *verified*, not merely asserted.

Assessment baseline: 2026-11-18. See `FEATURE_MATRIX.md` and `GENLOGIN_TITAN_ASSESSMENT.md`. This checklist is deliberately not marked complete by passing unit tests or by matching promotional features.

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
- [ ] Windows headless Chromium isolation test **passed** on current head; a defined test exists but still requires CI results.
- [ ] Windows headed actual Chrome, Edge and bundled Chromium tests on a fresh VM.
- [ ] Locally installed benign extension launch test with observed service worker and permissions.
- [ ] GUI interaction smoke / screenshot comparison / usability acceptance.
- [ ] Concurrency, storage corruption, disk-full, emergency shutdown, proxy failure and application reinstall.

## Release decision

Only after all necessary gates are demonstrated can CI be changed to produce a Windows EXE. The GitHub Actions workflow currently **does not** build binaries. Existing older EXEs are historical development builds, not a validated parity release.
