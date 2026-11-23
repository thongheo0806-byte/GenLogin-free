# GenLogin / Titan baseline: evidence-driven comparison (HOLD)

**Reviewed 2026-11-23. This is NOT a parity certificate.** The official
[GenLogin release notes](https://genlogin.com/release-notes) list
**v4.5.1 dated 06/08/2026** as the latest public entry checked on
2026-11-23. This public listing does **not** supply an inspected installer,
a Windows executable SHA-256, entitlement/edition, legal authorization for
binary analysis or independently witnessed Titan behavior. No such reference
has been provided to this project.

## Current AutumnGenLogin capability, not Titan equivalence

| Area | Source and executed development evidence | Remaining acceptance blocker |
|---|---|---|
| Profile catalog, groups, local browser sessions | SQLite catalog, per-profile persisted browser folders, explicit OS locks; real Windows Chromium integration, Chrome/Edge and Firefox/WebKit smoke lanes | No pinned GenLogin binary comparison; stress, abnormal exits, cross-version migration, rendering and portability are still incomplete |
| Runtime I/O isolation | One owning Playwright asyncio thread; worker-thread keyring, extension, scheduled completion and dedicated owner-thread profile leases (PR #44, Windows CI) | Prolonged disk-lock fault injection and whole-app shutdown under load still not exhaustively accepted |
| Recorder and replay | Opt-in DOM event review, fully blanked input/select values; tab/iframe capture and strict live Page/Frame identities, plus unique-target Chromium negative tests (PR #46) | Only **same open browser session**. No durable cross-session tab mapping, complete navigation/content identity, desktop-wide capture, full action support or GenLogin recording parity |
| Local live click synchronization | Up to five followers and 50 master gestures, specially marked synthetic localhost buttons; matching tab count, route/query and iframe documents, verified by real Chromium (PRs #41, #47) | **Not** arbitrary-site Sync Actions, navigation, text, keyboard, scroll, cookies, credentials or GenLogin/Titan live synchronizer parity |
| Visual workflow, graph, schedule and batch | Bounded JSON action set, Tk step editor and graph, persistent schedules and bounded batch journal, real Windows Chromium and GUI tests | Does not cover the vendor's full node catalog, cloud phone, complete action set, remote recovery or long-run/production fault matrix |
| Screenshot-based image click | Opt-in local OpenCV template matching and real Chromium synthetic click test; no cloud OCR/API is invoked | Not video automation or robust visual-target parity; zoom, layout and anti-aliasing may cause errors |
| Cloud/team metadata conflict resolution | Self-hosted encrypted metadata/workflow hub with RBAC and optimistic CAS; three-way Push and fail-closed Pull, atomic SQLite preview check, Win32 pointer test (PRs #39, #45, #48) | Not vendor cloud storage/protocol, automatic live browser-session sync, CRDT, complete disaster recovery or production hosted service certification |
| Browser-session archive transfer | Explicit dual-encrypted `.aglb` handoff, resumable UUID upload, server revocation, manual new-profile restore; strengthened versioned KDF and cache pruning (PRs #34, #37) | 16 MiB cloud-handoff limit; no automatic full GenLogin-style profile synchronization or portable Titan identity |
| Local API and extensions | Authenticated loopback API; manual MV3 extension import, opt-in Ed25519 publisher trust, extension version migration and rollback | No official GenLogin API compatibility, Web Store-equivalent automatic installs, comprehensive publisher audit or distribution review |
| GUI acceptance | Actual Windows top-level HWND/minimize/restore, OS mouse/keyboard Create Profile, real pointer graph editing, Cloud Pull conflict click (PRs #42, #48), structural Tk smoke | DPI/multi-monitor, high-contrast, keyboard-only and screen-reader accessibility, complete failure/recovery usability tests are pending |
| AI lab | Isolated synthetic browser-use/Ollama experiment. Actual local Ollama **inference** was executed in Docker; the small models did **not** produce a verified synthetic fixture button click (negative runs below) | Real browser-use agent task completion, approved model/image digests, runtime egress audit, long-run proof and production isolation review are missing. Lab is NOT a production app feature |
| Titan rendering / fingerprint behavior | **No Titan implementation or verified differential runtime evidence.** Stock Playwright Chrome/Edge/Firefox/WebKit adapters are not the proprietary Titan engine | Authorized pinned binary, legally permitted real observations, measured Windows profile/network/locale/WebRTC behavior and independent evaluation required |
| GenLogin Cloudphone/Marketplace and vendor extras | **Not implemented as matching products** | Feature parity not established |

### Executed evidence, with strict interpretation

- PR [#44](https://github.com/thongheo0806-byte/GenLogin-free/pull/44):
  async, worker-owned profile locks. Shared event loop heartbeat and lock
  cancellation regressions do not prove every filesystem failure mode.
- PRs [#45](https://github.com/thongheo0806-byte/GenLogin-free/pull/45),
  [#46](https://github.com/thongheo0806-byte/GenLogin-free/pull/46),
  [#47](https://github.com/thongheo0806-byte/GenLogin-free/pull/47) and
  [#48](https://github.com/thongheo0806-byte/GenLogin-free/pull/48):
  Windows CI 8/8 on each PR head, including synthetic profile conflicts,
  real Chromium tab/frame/replay and QA routing regressions and actual
  Win32 pointer UI tests. The corresponding combined `main` runs must
  always be verified separately after every merge.
- Real isolated Ollama inference but **failed browser-use agent** evidence:
  [run 45140938605](https://github.com/thongheo0806-byte/GenLogin-free/actions/runs/45140938605),
  [run 45141482823](https://github.com/thongheo0806-byte/GenLogin-free/actions/runs/45141482823),
  [run 45142114583](https://github.com/thongheo0806-byte/GenLogin-free/actions/runs/45142114583).
  A model emitting `TEST-OK` without the synthetic webpage's server
  observing a real click is a **negative acceptance result**, never a pass.
  An opt-in follow-up runtime-proof workflow is under review in PR #43;
  ordinary CI green does not change that agent result.
- GenLogin public sources: [release notes](https://genlogin.com/release-notes),
  [profile overview](https://docs.genlogin.com/group-profiles/create-profile/overview),
  [network/WebRTC](https://docs.genlogin.com/group-profiles/create-profile/network-and-webrtc),
  [local/cloud profiles](https://docs.genlogin.com/group-profiles/local-and-cloud-profiles),
  [profile sharing](https://docs.genlogin.com/group-profiles/share-profile),
  [automation](https://genlogin.com/automation),
  [official API](https://docs.genlogin.com/genlogin-api/profile-api/1.-profile-list).
  These describe advertised scope, not observed behavior of an exact
  installed vendor binary.

## What must happen before an equivalence decision

1. Obtain a **lawfully licensed, exact** GenLogin edition/build and record
   its installer provenance, SHA-256, OS/browser versions and permission for
   user-visible comparative testing. Written authorization is required
   for invasive inspection; no copied proprietary code, tampering or evasion.
2. Execute the same non-sensitive synthetic workflows on pinned Windows
   machines: reopen/persist, proxy/DNS/WebRTC outcomes, locale/timezone,
   extensions, recorder/navigation, sync, conflict recovery, crash/disk
   faults, accessibility, update/uninstall and resource use.
3. Retain hashes and independently witnessed pass/fail observations for
   all required cases. A matching Chromium version, screenshot, user-agent
   string or an internally green CI is **not** Titan parity.
4. Complete all security, license, artifact provenance and usability gates.
   Run `python -m autumn_genlogin.titan_evidence
   examples/titan/reference-evidence-template.json` as an **intake
   validator only**. Even a filled all-pass file yields at most
   `needs-independent-human-review`, never automatic release approval.

**Decision: HOLD EXE BUILD. No GenLogin/Titan, fingerprint-anonymity or
anti-Sybil guarantee.** See [RELEASE_GATES.md](RELEASE_GATES.md),
[FEATURE_MATRIX.md](FEATURE_MATRIX.md) and
[TITAN_VERIFICATION_PROTOCOL.md](TITAN_VERIFICATION_PROTOCOL.md).
