# Candidate GitHub open-source integrations for AutumnGenLogin

Research snapshot: **2026-11-20**. Public GitHub repository metadata and
published project documentation only. **No third-party project source has
been copied or vendored into AutumnGenLogin.** Versions, transitive licenses
and deployment requirements must be rechecked before a release.

The current app is Python 3.12, Tkinter, a single Playwright async driver,
SQLite, an opt-in local API, and independent persistent browser contexts.
Adopting a different full browser runtime or frontend is a much larger
architectural migration than integrating a focused library.

| Repository | Public GitHub license | Candidate feature | Decision / interface |
|---|---|---|---|
| [opencv/opencv](https://github.com/opencv/opencv) | Apache-2.0 | Click by visual pattern in a screenshot | **Incremental adoption in this PR:** optional Python OpenCV wheel, local PNGs keyed by SHA-256, bounded and unique matches, real Chromium proof |
| [browser-use/browser-use](https://github.com/browser-use/browser-use) | MIT | AI task planning / browser interaction | **Evaluate separately**, pinned exact version and isolated execution process; agent-supplied code, third-party LLMs and screenshot/secret egress are unacceptable by default |
| [OpenAdaptAI/OpenAdapt](https://github.com/OpenAdaptAI/OpenAdapt) | MIT | Improved recorder, demo-to-workflow compilation, deterministic replay and verification | **Study integration**, prefer translating an explicit consented recording into existing validated JSON/graph schema; avoid unnecessary global desktop capture |
| [pywinauto/pywinauto](https://github.com/pywinauto/pywinauto) | BSD-3-Clause | Windows GUI automation, keyboard access and UIA acceptance tests | **High-priority QA**, test in a genuine interactive Windows desktop and skip explicitly on non-interactive hosted runners |
| [microsoft/playwright](https://github.com/microsoft/playwright) | Apache-2.0 | Cross-browser DOM/locator automation | **Already in use** through its Python package; favor official APIs over duplicating an engine or transplanting another CDP driver |
| [browserbase/stagehand](https://github.com/browserbase/stagehand) | MIT | AI-assisted element interaction and extraction | **Research only**; TypeScript-oriented, a separate service/bridge would need strict local authentication and reliability tests |
| [xyflow/xyflow](https://github.com/xyflow/xyflow) | MIT | Rich node editor, groups, ports, zoom and navigation | **Conditional** upon explicitly choosing a WebView/React GUI migration; existing Tk node editor cannot directly import React components |
| [open-telemetry/opentelemetry-python](https://github.com/open-telemetry/opentelemetry-python) | Apache-2.0 | Workflow timing, error diagnosis and traces | **Future**, local-only opt-in diagnostics; exclude cookies, page data, authentication and secret span attributes |
| [robocorp/robocorp](https://github.com/robocorp/robocorp) | Apache-2.0 | Structured RPA workflows, retries and task outcomes | **Prototype only**, evaluate scheduler overlap with existing graph and dependency complexity |
| [Tesseract-OCR/tesseract](https://github.com/tesseract-ocr/tesseract) | Apache-2.0 | OCR-based visual actions and text recognition | **Later**, Windows native binaries and language models, screenshot privacy, OCR confidence and localization must be validated |

## Excluded from automatic copy/integration

- [Skyvern-AI/skyvern](https://github.com/Skyvern-AI/skyvern)
  is currently listed **AGPL-3.0** on GitHub. Strong AI/Playwright
  ideas, but this is not a drop-in permissive library. Review AGPL obligations
  and process boundaries before using any code.
- [AutomaApp/automa](https://github.com/AutomaApp/automa)
  describes AGPL and commercial licensing rather than a uniformly permissive
  codebase. Inspect specific files and licensing before any code transfer.
- [microsoft/OmniParser](https://github.com/microsoft/OmniParser)
  is listed **CC-BY-4.0** at repository level; models and weights may have
  independent terms and hardware/runtime implications. No assumption of
  automatic commercial compatibility or production Windows readiness.

## Staged implementation priorities

1. **Local visual click:** user imports an explicit PNG from disk, which is
   checked, stored as an immutable hash-addressed asset and referenced by
   `click_image` in a validated workflow. Use Playwright `scale="css"`
   viewport screenshots, OpenCV's `matchTemplate` only inside the running
   application, reject missing/multiple high-confidence targets, and click
   with native Playwright mouse coordinates. Optional dependency must not be
   required for users who only need DOM actions. Tests must cover unique,
   duplicate, low-detail, tampered and absent assets, plus actual Chromium.
2. **Windows UIA testing via pywinauto:** make interactable desktop runner
   provision explicit, verify major profile/editor workflows, focus and
   keyboard behavior; never claim headless Tk smoke is accessibility proof.
3. **Recorder improvements via OpenAdapt concepts:** request opt-in consent,
   redact typed secrets, capture page/element structure, maintain a bounded
   replay schema, test navigation/frame boundaries and user review.
4. **AI agent experiment:** separate process with a restrictive permission
   model, policy-controlled local-browser scope, human approval for irreversible
   actions and network exposure, no default page upload. Measure success and
   failure, LLM price, telemetry, recovery and secrets before enabling.
5. **Operational reliability:** test browser crash, storage pressure,
   per-profile concurrency, JSON graph safety, long-running schedules, live
   sync and recovery with negative-path assertions.
6. **Optional future UI migration:** only if browser-based app shell is approved
   and can preserve native Windows local-data and security guarantees.

## Integration and license gates

- Record exact upstream project commit / release, SPDX license text,
  version pin, Python/Windows packaging support, third-party dependency
  attribution and software bill of materials before shipping anything.
- New dependencies should be optional when feasible, use no implicit
  telemetry/cloud account, and fail clearly if absent.
- Never share private browser session state, screenshots, API tokens, proxy
  credentials or extracted page text with external services by default.
- User-approved UI automation and workflows do not include bypassing
  anti-fraud, platform enforcement, identity checks or copying a proprietary
  fingerprint browser. A permissive repository **does not** prove GenLogin
  or Titan functional parity.
- **Keep the EXE build gate on HOLD** until independent, legally authorized
  reference testing and all release acceptance requirements pass.

Source and evaluation checklist:
[FEATURE_MATRIX](FEATURE_MATRIX.md),
[RELEASE_GATES](RELEASE_GATES.md),
[ENGINE_LICENSING](ENGINE_LICENSING.md).
