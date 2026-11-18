# AutumnGenLogin 🌙

> **RELEASE HOLD as of 2026-11-18:** This repository contains **development source**, not a verified GenLogin-parity release. No EXE will be built or released until the [release gates](docs/RELEASE_GATES.md) have passed. The CI workflow deliberately performs tests only. Historical EXEs are not parity-certified.

**Free, local-first browser profile studio for Windows**. This is an independent open-source implementation inspired by the *category* of browser profile managers. **Not affiliated with GenLogin; not a clone of its proprietary browser engine.**

**Project status: v0.4.1-dev, incomplete feature parity.** This development branch adds a sequential visual workflow builder, opt-in local Manifest V3 extensions for Playwright Chromium, and Windows browser/GUI integration tests. The release build is disabled; a passing test is not an approval to ship.

## Current features

**Reliability changes since v0.3:** Cross-process profile locking to guard against concurrent use of one browser data folder; refuses deletion of profiles still open in another process. A read-only, offline Diagnostics command and GUI button check SQLite health, disk space and orphaned browser folders without reading browser sessions or network access.

- Create, edit, clone, group, tag, search, import and export browser profile **metadata**.
- Launch independent Chrome/Edge/Playwright Chromium sessions with distinct persistent `user_data_dir` folders (cookies, history and sessions isolated by directory).
- Set locale, timezone, viewport, optional user agent, start URL, and per-profile HTTP/SOCKS5 proxy. Proxy passwords are stored via the OS credential vault (`keyring`), not in SQLite or export JSON.
- Run up to six browser sessions at once, with independent worker threads. Bulk-open one selected group from the desktop UI.
- Build and run a JSON workflow without executing untrusted code: `goto`, `click`, `fill`, `press`, `check`, `uncheck`, `select_option`, `scroll_into_view`, `wait`, `wait_for`, `extract_text`, `screenshot`. Cancel between steps.
- Save screenshots in a per-profile local directory.
- Opt-in, loopback-only HTTP API with a fresh bearer token per startup. **Off by default**.
- SQLite metadata stored locally, no subscription, no login, no cloud sync or tracking service.
- A Windows GitHub Actions workflow runs unit tests, builds `AutumnGenLogin.exe` with PyInstaller, smoke-tests the packaged app and uploads the artifact.

## Quick start: Windows (source)

1. Install **Python 3.12** and **Google Chrome or Microsoft Edge**.
2. Clone/download this repository and open PowerShell in its directory. Alternatively, double-click `START-WINDOWS.cmd` to install runtime dependencies and launch.
3. Run:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python main.py
   ```

4. Click **+ New profile**, choose `chrome` or `msedge`, save the profile, select it and click **Open**.
5. To use browser engine `chromium` instead, install Playwright's browser separately: `python -m playwright install chromium` (in the same Python environment). **The bundled single-file EXE does not include a Chromium browser**; Chrome/Edge installed on the computer is the recommended mode.

## EXE release is disabled pending feature parity

The user requires a **demonstrated GenLogin-equivalent application** before any new executable is built. The `main` GitHub Actions workflow runs unit tests, application self-checks, Tkinter UI smoke checks, and a real Chromium isolation and benign extension test. It deliberately has **no EXE packaging job**.

`BUILD-EXE-WINDOWS.cmd` is a deliberately blocked release entrypoint. Do not re-enable packaging until the version-specific [release gates](docs/RELEASE_GATES.md), [feature matrix](docs/FEATURE_MATRIX.md) and [engine/legal checklist](docs/ENGINE_LICENSING.md) are met.

You may continue evaluating the Python source locally via `START-WINDOWS.cmd`, but this is development testing, not a parity release.

## Data locations and privacy

On Windows: `%LOCALAPPDATA%\AutumnGenLogin\`.

- `profiles.sqlite3`: profile metadata, without proxy passwords.
- `browser-data\<uuid>\`: browser-owned cookies, local storage and browsing sessions (sensitive; never commit this directory).
- `screenshots\<uuid>\`: workflow screenshots (also may contain sensitive data).
- Proxy passwords: Windows Credential Manager through `keyring`.
- `AUTUMN_GENLOGIN_HOME`: optional absolute local data directory override (for advanced users).

**Export** includes metadata only, not browser sessions, cookies or proxy passwords. **Clone** creates fresh browser state and does not carry credentials. Deletion is permanent and deletes local browser-state files. Consider backing up first.

## Automation example

Paste into the **Automation** tab, select an open profile and click **Run on selected profile**:

```json
[
  {"action": "goto", "url": "https://example.com"},
  {"action": "wait_for", "selector": "h1"},
  {"action": "extract_text", "selector": "h1"},
  {"action": "screenshot"}
]
```

Actions are validated before execution. Arbitrary JavaScript, Python, shell commands, `file://` and `javascript:` URLs are not supported in workflows.

## Local API (optional)

Click **API: OFF** to start a server *only* on `127.0.0.1:8765` and display the current token. The token changes every app launch. Requests require `Authorization: Bearer <token>`. There is no unauthenticated control endpoint.

```powershell
$token = 'COPY_TOKEN_FROM_APP'
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://127.0.0.1:8765/v1/health -Headers $headers
Invoke-RestMethod http://127.0.0.1:8765/v1/profiles -Headers $headers
# Replace PROFILE_UUID with an ID from /v1/profiles
Invoke-RestMethod http://127.0.0.1:8765/v1/profiles/PROFILE_UUID/open -Headers $headers -Method Post -ContentType 'application/json' -Body '{}'
```

Also available: `POST /v1/profiles/{id}/stop`, `POST /v1/profiles/{id}/cancel`, and `POST /v1/profiles/{id}/run` with `{"steps": [...]}`. These queue asynchronous browser actions; HTTP 202 means *accepted*, not completed. The API is not designed to be exposed to a LAN or the internet.

## Tests

```powershell
python -m unittest discover -s tests -v
python main.py --self-check
python main.py --doctor
python main.py --doctor-json
```

Unit tests cover profile validation, CRUD/export/import/backup, OS profile locking, offline diagnostics, flow validation and loopback API authorization/error cases. They do **not** yet establish actual GUI usability, Windows proxy compatibility, fingerprint equivalence, browser crash recovery, or signed release provenance.

## Comparison to GenLogin

| Feature | This repo v0.3.0 | Status |
|---|---|---|
| Persistent browser profile separation | Independent per-profile Chromium data dir | Implemented, platform QA pending |
| Profile manager, tags, groups, search, clone | Local SQLite + UI | Implemented |
| Proxy HTTP/SOCKS5 (including optional auth) | Playwright configuration + OS credential vault | Implemented, compatibility QA pending |
| Locale, timezone, viewport, user agent | Standard Playwright context options | Implemented |
| Visual drag/drop workflow builder | JSON workflow editor only | Not implemented |
| Deep stealth fingerprint engine / custom browser core | Standard Chrome/Edge/Chromium, no engine patch | **Not implemented** |
| Cloud sync / team role sharing | Local only | Not implemented |
| Marketplace / GenLogin-exclusive integrations | None | Not implemented |
| Browser extension management UI | None | Not implemented |
| Windows installer, signed EXE, automatic updates | GitHub Actions one-file build | Partially implemented |
| AI workflow assistant | No AI or external account required | Planned |

**No anti-detection guarantee:** IP, browser configuration and profile separation do not imply immunity to platform security systems. Use with sites you are authorized to access and comply with their terms. This repo does not implement CAPTCHA bypass, account farming or platform evasion.

For public-source feature comparisons and Sybil limitations, see [`docs/GENLOGIN_TITAN_ASSESSMENT.md`](docs/GENLOGIN_TITAN_ASSESSMENT.md). For design evidence, known gaps and priorities see [`docs/FEATURE_MATRIX.md`](docs/FEATURE_MATRIX.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) and [`docs/REA_EVIDENCE.md`](docs/REA_EVIDENCE.md).

## Acknowledgements and license

- Investigation approach: [REA by morluto](https://github.com/morluto/rea) (skill instructions, evidence-first methods, not a GenLogin desktop binary analysis).
- Architecture references: [Playwright persistent contexts](https://playwright.dev/python/docs/api/class-browsertype), [BrowserOpsLab browser profile manager](https://github.com/BrowserOpsLab/playwright-browser-profile-manager), [thePrivator](https://github.com/yanx9/thePrivator). The source here was independently implemented; third-party code was not copied.
- Licensed **MIT** for AutumnGenLogin original source. Dependencies retain their respective licenses.

**GenLogin** is a third-party product and brand. AutumnGenLogin does not use its source code, internal APIs, artwork, logos or proprietary fingerprints.

## Development update: extension library and visual workflow (not a parity release)

The current source adds a local Manifest V3 extension manager (manual ZIP/unpacked folder import, permission review, per-Chromium-profile attach/detach) and a sequential visual workflow builder (edit, duplicate, drag reorder, import/export validated JSON steps). Chrome/Edge no longer support command-line extension sideloading via the old flags. Use Playwright-managed Chromium for these manual extensions; an extension package is arbitrary executable code and should only be installed after reviewing its provenance and requested permissions.

The repo's Windows workflow is now **test-only**, with an explicit real Chromium isolation smoke lane. Do **not** interpret passing unit tests as an endorsement of production readiness or GenLogin/Titan feature equivalence. See [strict release gates](docs/RELEASE_GATES.md), [feature matrix](docs/FEATURE_MATRIX.md), [license and engine notes](docs/ENGINE_LICENSING.md).
