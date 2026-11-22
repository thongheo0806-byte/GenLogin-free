# Recorder review and Windows GUI automation QA

Engineering snapshot: **2026-11-21**. Source-only development milestone.
**Do not build EXE** before [release gates](RELEASE_GATES.md).

## OpenAdapt-informed recording design

Upstream references:
- [OpenAdapt](https://github.com/OpenAdaptAI/OpenAdapt), MIT, design ideas:
  observation, scrubbing, compile/review and separate replay.
- [OpenAdapt browser recording](https://github.com/OpenAdaptAI/openadapt-flow/blob/main/docs/BROWSER_RECORDING.md), the importance of explicit browser scope and treating screenshots/secret fields as sensitive.
- [pywinauto](https://github.com/pywinauto/pywinauto), BSD-3-Clause, Win32 and UIA Windows desktop automation.

AutumnGenLogin independently implements a **small structural DOM recorder** with the
existing Playwright driver. We did not vendor or execute OpenAdapt's capture stack
and we did not add desktop-wide mouse/keyboard monitoring.

1. Select and open an explicit browser profile, then press **Record** in
   Automation. Each recorder session belongs only to the selected persistent
   browser context and starts empty.
2. The injected listener emits the locator of clicks on controls, select
   changes, checkbox changes, blank fill actions and a narrow Escape key
   action. It does **not** read or emit field values, screenshots or URLs.
3. An exposed Playwright binding is callable by the page and therefore
   **untrusted**. Python accepts only allowlisted action types with valid
   selectors, overwrites submitted text/selected values with safe placeholders
   even if the page fabricates a payload, and ignores nested frame payloads
   that the existing top-frame runner cannot safely replay.
4. A navigation event is counted **without retaining any URL/path/query**.
   SPA history updates may not increment the count. Replaying a saved
   workflow will not automatically navigate to the same page.
5. **Stop recording → Use recording** opens an explicit human review summary:
   action count, number of redacted form actions and observed page loads.
   Cancel keeps the previous workflow unchanged. Accepting imports an
   *editable* draft. Users must fill placeholders, add reviewed URL/page
   assertions, and inspect all click targets before running.
6. No recorder data is persisted automatically. Explicit workflow export
   will save user-reviewed selectors and action JSON. The local API
   `GET /v1/profiles/{id}/recording` remains token protected.

### Security / accuracy limitations

- A website can manipulate DOM IDs, class names or accessible attributes;
  no selector compiled from an untrusted page can be assumed trustworthy.
- Cookies/typed values are intentionally not captured; reproducing a workflow
  requires a user to re-enter authorized values. No automatic credential
  learning or secure-input replay is implemented.
- No frame switching, resilient multi-tab targeting, SPA route fidelity,
  OCR/video capture or action outcome verification is claimed.
- A reviewed recorder draft is **not** authorization to run actions on
  unrelated websites and cannot prove a third-party site processed a click.
- The feature does not implement desktop RPA parity with OpenAdapt, GenLogin
  or proprietary Titan fingerprint behavior.

## Windows pywinauto acceptance scope

The `windows-pywinauto-smoke` job installs pywinauto as a **test-only**
dependency on the Windows GitHub runner. The test:
- Launches an actual, visible Tkinter `AutumnGenLogin` app with temporary
  synthetic profile data.
- Discovers its top-level HWND via pywinauto's Win32 desktop enumeration,
  checks window title, enabled state, visibility and dimensions.
- Requests real Win32 minimize and restore and verifies OS window state.
- Checks the main UI modules remain initialized after window transitions.

It is not the preexisting Tk structure-only test. It also **is not** a
complete UI Automation accessibility audit, reliable screenshot/keyboard
interaction test or proof of keyboard focus behavior under a remote/locked
desktop. Deeper acceptance requires a fresh Windows VM with an active,
unlocked, accessible interactive desktop and human-reviewed results.

### CI acceptance

- Unit test `test_recorder_review.py`: malicious page payload, redaction,
  deduplication, invalid selectors/events, navigation summary.
- Real Playwright Chromium test in
  `test_shared_browser_integration.py`: attempts an invalid navigation
  through the exposed binding and submits private form values, reloads page,
  records a button click and checks no sensitive value or URL is retained.
- Windows GUI pywinauto job: actual Windows HWND state.
- All other original Windows CI lanes must continue to pass, including
  Chrome/Edge, Firefox/WebKit, old Windows environment upgrade.

## 2026-11-22 real Win32 input acceptance expansion

The Windows pywinauto job now has a second end-to-end test beyond
minimize/restore. It enumerates the **real** top-level Tk app, sends a
Win32 mouse click to the visible **+ New profile** button (using its
live screen coordinates), checks the OS exposes a **Create profile**
dialog, uses actual Windows keyboard input to replace the synthetic
profile name, and clicks **Save profile**. It then checks the profile
appeared in SQLite and the visible Treeview. The test does not call
`App.new_profile`/`ProfileEditor.save` directly.

This is a basic interaction regression, not a production accessibility
certification or equivalent to auditing every control/tab/window for
keyboard-only navigation, high DPI, multiple monitors, localization,
high-contrast mode or screen readers. It requires an interactive Windows
desktop session. If a hosted runner cannot inject physical input,
CI must report that limitation rather than silently counting an
unexecuted test as a success.
