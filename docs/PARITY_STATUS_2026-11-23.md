# AutumnGenLogin vs published GenLogin/Titan: evidence status

**Date:** 2026-11-23. **Disposition:** HOLD EXE BUILD.
**Comparison method:** source/CI evidence for AutumnGenLogin and public GenLogin
release notes/documentation ONLY, NOT a controlled vendor-binary comparison.

Published GenLogin reference: https://genlogin.com/release-notes currently lists
v4.5.1, dated `06/08/2026`. Public descriptions are **not** verification of
actual installed behavior, proprietary implementation or a legal license to
inspect/redistribute Titan. A pinned, authorized binary and independent
Windows observations have NOT been supplied.

| Capability | AutumnGenLogin evidence | Important gap |
|---|---|---|
| Profiles, groups, isolated persistent sessions | Windows Chromium + multi-engine CI, SQLite, profile locks, local encrypted v2 backup, batch/scheduler | Real aging profiles, large crashes, complete migration and operator UX |
| Recorder | PR #38: real Chromium second-tab/iframe structural capture and replay; form values redacted | Tab ordinal not semantic identity; selector/navigation drift; complex user gestures |
| Visual workflow & automation | Bounded nodes, variable/capture support, local API, image-click | Different node catalog, support and programming contracts |
| Live Synchronizer | PR #41: 1 master, up to 5 followers, **localhost-only marked synthetic buttons**, matching tabs/iframes | Not full real-web typing, scrolling, navigating, keyboard, account or session sync |
| Cloud | PR #39: signed-in encrypted metadata/workflow team sync, three-way conflict checks, revision compare-and-swap; manual small encrypted session handoff | No automatic cloud-browser session sync, large storage, disaster recovery SLA |
| Multi-engine | CI lanes launch installed Chrome, Edge, Firefox, WebKit, Chromium through supported Playwright engines | Not Titan engine; no fingerprint or comprehensive DNS/WebRTC parity |
| Windows GUI | PR #42: Win32 input-driven workflow row actions, Tk-safe backup/import/export workers | Screen-reader/keyboard-only/a11y, display scaling, live operator, power-loss resilience |
| Shared Playwright loop | PR #40 offloads disk-image and scheduler-journal I/O; follow-up worker-owned OS locks in independent PR | Still require complete race/cancellation/fault-injection review |
| AI automation | Docker-isolated `browser-use==1.0.7` synthetic fixture and real Ollama inference proof | Running a model is not proof an agent clicked; no production AI integration |
| Titan fingerprint engine | **Not implemented or verified** | Pinned authorized reference binary, license, differential tests, independent review |
| GenLogin API contract | Independent localhost `/v1` API and SDK | Not protocol-compatible with proprietary GenLogin API |
| Signed Windows release | Source-only CI, no new EXE | Signing, lockfiles, crash-recovery, real-machine verification, authorization |

## Real AI lab evidence, not a marketing claim

- Workflow: https://github.com/thongheo0806-byte/GenLogin-free/actions/runs/45140938605
  successfully provisioned a public local model, passed the Compose isolation
  contract and **executed real Ollama inference** in a network-internal Docker
  container; the synthetic browser-use agent **did not verify** a click.
- Follow-up: https://github.com/thongheo0806-byte/GenLogin-free/actions/runs/45141482823
  explicitly observed `button_clicked=false`, `model_report_marker=true`.
  This demonstrates why an LLM answer is **not** evidence of completed browser
  work. Model output, page secrets, browser profile and user credentials were
  not logged. The model weights were ephemeral.
- A stronger model can be tested only through an independently inspected run.
  No pass or completion is inferred from merely invoking the workflow.

## Why there is no credible parity percentage

There is no authorized GenLogin/Titan binary, pinned feature-acceptance suite,
matched Windows runtime, signed reference artifacts or independent witness.
Counting similarly named UI buttons would be misleading. Until these exist,
a meaningful equivalence percentage is mathematically and experimentally
undefined.

To proceed lawfully, follow
`docs/TITAN_VERIFICATION_PROTOCOL.md` and the offline
`examples/titan/reference-evidence-template.json`. The validator intentionally
cannot authorize an EXE by itself. No anti-fraud/Sybil resistance or Titan
engine equivalence is implied.
