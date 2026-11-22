# AutumnGenLogin 🌙

> **RELEASE HOLD as of 2026-11-18:** This repository contains **development source**, not a verified GenLogin-parity release. No EXE will be built or released until the [release gates](docs/RELEASE_GATES.md) have passed. The CI workflow deliberately performs tests only. Historical EXEs are not parity-certified.

**Free, local-first browser profile studio for Windows**. This is an independent open-source implementation inspired by the *category* of browser profile managers. **Not affiliated with GenLogin; not a clone of its proprietary browser engine.**

**Project status: v0.5 development baseline, updated 2026-11-20; incomplete feature parity.** This development branch includes a draggable node graph, recorder, opt-in encrypted team metadata hub, durable local scheduler, five engine adapters, shared Playwright driver and Windows regression tests. The release build is disabled; a passing test is not an approval to ship.


## Titan / GenLogin parity verification: evidence HOLD

A non-invasive JSON evidence readiness checker now blocks any assertion of Titan equivalence without a pinned, legally observed GenLogin/Titan baseline, reference/Autumn test artifacts and outside reviewer sign-off. Run `python -m autumn_genlogin.titan_evidence examples/titan/reference-evidence-template.json`; its default result remains **blocked**, and it cannot authorize an EXE even with all self-reported cases marked pass. See [Titan comparison protocol](docs/TITAN_VERIFICATION_PROTOCOL.md). The actual proprietary engine has not been inspected or reproduced.

## Manual encrypted cloud session handoff (development)

The Team Sync tab can now manually transfer an **already encrypted** `.aglb` browser profile backup to a permitted team member through the self-hosted TeamHub. Select **Upload encrypted session backup** (owner/editor role), then share the generated transfer UUID. The recipient selects **Download encrypted session backup** (viewer role or above) and saves the original encrypted bytes to a **new local file**. Restoring remains a separate explicit **Restore backup** action requiring the original archive passphrase; it creates a new profile and never overwrites an existing one. The server holds only AES-GCM ciphertext inside encrypted, revision-checked, immutable documents, and the upload/download requires a separate shared team passphrase. Maximum 16 MiB per archive and 64 parts. If upload disconnects, the GUI can explicitly resume under a transfer UUID that was copied **before upload**; it verifies existing encrypted chunks against the unchanged `.aglb` file and never overwrites conflicting versions. Team owner/admin may now **Revoke team archive**, which atomically removes encrypted Hub copies and permanently blocks reuse of the handoff UUID; it **cannot** delete downloaded copies or invalidate real website sessions. No automatic session sync, background replay, live credential syncing or production cloud availability is claimed. See [manual session handoff](docs/CLOUD_SESSION_HANDOFF.md).

## Local reviewed Miniapps catalog (development)

The **Miniapps** tab imports small declarative JSON packages from files you explicitly select, including optional `AutumnGenLogin/signed-miniapp-1` envelopes signed by an Ed25519 key that the user has explicitly pinned and verified out of band. The application checks the exact manifest, validates every workflow step, rejects embedded code and pre-filled form values, stores a SHA-256-identified immutable copy in local SQLite and displays the required navigation origins. **Import never executes an action.** Preview and confirm **Load draft** to copy its steps into the editable Automation builder, then review and run separately. A sample is at [examples/miniapps/inspect-example-com.json](examples/miniapps/inspect-example-com.json). The UI displays unsigned/trusted/untrusted status, supports manually trusted signing keys and blocks signed-package loading after key revocation. Signatures prove possession of the pinned key, **not a real-world publisher identity or workflow safety**. There is no remote store, publisher certificate authority, package discovery or automatic updates. See [Miniapps security and scope](docs/MINIAPPS.md).

## Local QA live click mirroring (experimental)

A new **Local QA sync** tab can mirror clicks of explicitly marked test buttons from one open master profile to 1-5 open follower profiles in the same group. All profiles must show the **same `http://127.0.0.1:port` origin**. This is a **localhost-only verification feature** for a user-controlled synthetic test page, not a general-purpose GenLogin synchronizer and not intended for real accounts. It never copies passwords, typed values, page URLs, cookies, keyboard input or browser fingerprints. Test pages must mark eligible buttons with `data-autumn-qa-click="1"` and a simple ID. See [local QA synchronizer](docs/LOCAL_QA_SYNCHRONIZER.md).

## Experimental isolated browser-use AI lab (NOT a product feature)

The `experiments/browser_use_lab/` project contains a **separate, opt-in research experiment** using exactly pinned `browser-use==1.0.7` and an operator-prepared local Ollama model. The model-generated agent may execute Python, so there is **no safe direct integration with user profile data**. The lab operates only on its own synthetic localhost test page inside a restricted Docker Compose internal network with no application data mounts, no host ports, telemetry disabled and a new temporary browser. CI validates the security policy and Compose configuration only; it **does not claim a successful real LLM inference run**.

See [AI sandbox lab](docs/AI_LAB_ISOLATION.md). Do not use this on real websites or personal accounts.

## Optional local image-click automation (development)

An **opt-in** image-matching action is available using OpenCV without sending screenshots to an external service. Install separately:

```powershell
python -m pip install -r requirements-vision.txt
```

Open **Automation** → **Import image** and select a distinctive PNG target cropped to 16-256 pixels, maximum 256 KiB. The app saves a SHA-256-identified local copy and copies its ID to your clipboard. Use the following step in the Visual builder, JSON editor or a graph action node:

```json
{"action":"click_image","template_id":"PASTE_64_CHARACTER_SHA256_ID_HERE","confidence":0.94}
```

Use the exact SHA-256 ID generated by the import dialog. During execution, Playwright takes a CSS-pixel-scaled **viewport-only** screenshot in memory. OpenCV matches it locally and the click is allowed only for one sufficiently confident target. Missing/multiple matches fail with an explicit error; no arbitrary image file path, script or screenshot upload is accepted by the workflow. This is deliberately not a multi-scale detector, OCR engine, AI vision model or a guaranteed match after zoom/theme/layout changes. Do not import images showing private information.

See [GitHub library integration research](docs/OPEN_SOURCE_INTEGRATIONS.md) for vetted upstream sources, license notes and future priorities.

## 2026-11-20 development milestones (still NO EXE release)

- **Encrypted offline profile backups:** backup a *stopped* profile including sensitive browser-session files into an AES-GCM encrypted `.aglb` archive; restore as a **new** profile. User-owned passphrase is required and not recoverable. OS vault passwords, proxy credentials and extension packages are excluded. Limited to 1 GiB of browser data / 12,000 files. Only use on trusted storage.
- **Offline MV3 extension update and rollback:** import a reviewed ZIP as a new immutable package; compare permission increases before confirming migration of stopped Chromium profiles. A prior package is retained for explicit rollback. This is not signed-publisher or Web Store verification.
- **Scheduler results and batch tasks:** terminal run journal, local bearer-authenticated schedule history, bounded multi-profile group batches (1-6 concurrent), and cancellation of in-flight Playwright waits.
- **Python local API client SDK:** safe typed client for the existing `/v1` API, with redirect/proxy refusal, strict loopback URLs and typed HTTP errors. See [API SDK](docs/API_SDK.md). **Not GenLogin API compatible.**

## v0.5-dev functional expansion (source only)

- **Node graph designer:** drag nodes on a canvas, link labelled branches, edit actions and validate before running; conditions check for element existence and repeat nodes have bounded loops. Open Automation → **Node graph**.
- **Recorder:** open a profile, choose **Record**, interact, **Stop recording**, then **Use recording**. A mandatory review warns about blank form values, placeholder select options and page loads. Only the selected profile's main-frame DOM events are eligible, and typed values/URLs are never recorded. The preview is an editable draft, **not proof of successful replay**. See [Recorder and Windows QA](docs/RECORDER_WINDOWS_QA.md).
- **Durable scheduler:** Scheduler tab schedules the current visual/graph/JSON workflow for a selected profile, once or at a whole-minute recurring interval. Scheduled runs operate while the desktop app remains open; missed intervals are skipped.
- **Team sync (self-hosted):** `python main.py --hub` runs an opt-in loopback service on port 8899; the Team Sync tab supports register, login, team creation, invites, and encrypted manual push/pull of profile metadata or a workflow. See [Team Sync security and setup](docs/TEAM_SYNC_OPERATIONS.md). **This does not sync browser sessions, cookies or proxy passwords.**
- **Five browser engines:** Playwright Chromium, Chrome, Edge, Firefox and WebKit are selectable. For Firefox/WebKit run `python -m playwright install firefox webkit`. Only bundled Chromium supports unpacked extensions. See [0.5 feature/evidence matrix](docs/FEATURES_050.md).
- **Performance architecture:** a single asynchronous Playwright driver runs independent contexts, rather than one Node driver per profile. SQLite connection reuse is enabled in the desktop app and is scoped to individual threads.

**Important:** These additions are not evidence of full GenLogin/Titan feature equivalence. There is **no new EXE build**. See [public GenLogin feature-parity assessment](docs/GENLOGIN_TITAN_ASSESSMENT.md), [Titan evidence protocol](docs/TITAN_VERIFICATION_PROTOCOL.md) and [release gates](docs/RELEASE_GATES.md).

## Current features

**Reliability since v0.3:** Cross-process profile locking guards concurrent browser access. The 2026-11-19 audit fix adds browser-close detection and bounded event pumping, recovery-safe profile deletion (staging + database transaction + post-commit cleanup), corrupt/missing-database `--doctor` support, safe SQLite URIs and a version marker. Diagnostics do not read browser sessions or contact third-party services; a short-lived temporary file is used to check directory writability.

- Create, edit, clone, group, tag, search, import and export browser profile **metadata**.
- Launch independent Chrome/Edge/Playwright Chromium sessions with distinct persistent `user_data_dir` folders (cookies, history and sessions isolated by directory).
- Set locale, IANA timezone, viewport, optional user agent, start URL, and per-profile HTTP proxy (optional authentication) or SOCKS5 proxy (**no username/password authentication** in Chromium). Proxy passwords are stored via the OS credential vault (`keyring`), not in SQLite or export JSON.
- Run up to six browser sessions at once through a shared Playwright driver; batch-run a validated workflow across a selected group with bounded concurrency. Batch results are saved locally in SQLite with safe crash recovery and no automatic action replay.
- Build and run a JSON workflow without executing untrusted code: `goto`, `click`, `fill`, `press`, `check`, `uncheck`, `select_option`, `scroll_into_view`, `wait`, `wait_for`, `extract_text`, `screenshot`. Cancel between steps.
- Save screenshots in a per-profile local directory.
- Opt-in, loopback-only HTTP API with a fresh bearer token per startup. **Off by default**.
- SQLite metadata stored locally, no subscription or mandatory cloud login. Optional self-hosted encrypted metadata/workflow sync is disabled by default.
- Windows GitHub Actions tests unit/GUI structure and real Chromium, Chrome, Edge, Firefox and WebKit smoke; **EXE building and publishing remain disabled** until documented feature parity is evidenced.

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

Click **API: OFF** to start a server *only* on `127.0.0.1:8765` and display the current token. The token changes every app launch. Requests require `Authorization: Bearer <token>`. There is no unauthenticated control endpoint. Extracted text is potentially sensitive and is held in process memory, not activity logs; it is returned only to a client with the API bearer token.

```powershell
$token = 'COPY_TOKEN_FROM_APP'
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://127.0.0.1:8765/v1/health -Headers $headers
Invoke-RestMethod http://127.0.0.1:8765/v1/profiles -Headers $headers
# Replace PROFILE_UUID with an ID from /v1/profiles
Invoke-RestMethod http://127.0.0.1:8765/v1/profiles/PROFILE_UUID/open -Headers $headers -Method Post -ContentType 'application/json' -Body '{}'
```

Also available: `POST /v1/profiles/{id}/stop`, `POST /v1/profiles/{id}/cancel`, and `POST /v1/profiles/{id}/run` with `{"steps": [...]}`. These queue asynchronous browser actions; HTTP 202 means *accepted*, not completed. Read `GET /v1/profiles/{id}/runs/latest` to poll the status (`queued`, `running`, `succeeded`, `cancelled`, `failed`) and retrieve bounded `extract_text` output (up to 20 pieces of 4,096 characters; **sensitive; never share API token or results**). Only the latest run per profile is held in process memory. The API is not designed to be exposed to a LAN or the internet.

## Tests

```powershell
python -m unittest discover -s tests -v
python main.py --self-check
python main.py --doctor
python main.py --doctor-json
```

Unit tests include regressions for manually closing a browser window (Playwright stub), corruption and URI-edge-case diagnostics, two-phase profile deletion, vault rollback, data import atomicity, malformed API authorization/inputs, proxy compatibility and workflow JSON preservation. `test_browser_integration.py` now exercises `BrowserManager` itself when `AUTUMN_E2E=1`. **Until the current Windows CI succeeds, Chromium lifecycle behavior remains unverified.** The tests do not establish real proxy compatibility, browser crash resilience on every Windows build, proprietary-engine parity or release provenance.

## Comparison to GenLogin

| Feature | This repo v0.5-dev | Status |
|---|---|---|
| Persistent browser profile separation | Independent per-profile Chromium data dir | Implemented, platform QA pending |
| Profile manager, tags, groups, search, clone | Local SQLite + UI | Implemented |
| Proxy HTTP and SOCKS5 (no-auth) | Playwright configuration, verified validation; HTTP credentials in OS vault | Real proxy QA pending |
| Locale, timezone, viewport, user agent | Standard Playwright context options | Implemented |
| Visual drag/drop workflow builder | Sequential builder, graph nodes (conditions/repeats), browser recorder (selectors only) | Partial; not full GenLogin node catalog |
| Deep stealth fingerprint engine / custom browser core | Standard Chrome/Edge/Chromium, no engine patch | **Not implemented** |
| Cloud sync / team role sharing | Optional self-hosted encrypted metadata & workflow sync with role checks | Partial; no browser session/cloud GenLogin API parity |
| Marketplace / GenLogin-exclusive integrations | None | Not implemented |
| Browser extension management UI | Opt-in local MV3 folder/ZIP import and attach | Basic implemented; marketplace/update missing |
| Windows installer, signed EXE, automatic updates | CI tests only, release gate enforced | Not implemented/release on hold |
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

## 2026-11-19 engineering audit

See [audit remediation report](docs/AUDIT_2026-11-19.md) for exact regression tests, unresolved risks and verification status. Fixes were based on the source at commit `3d6367f81162`; the original reproduction script path belonged to another environment and was not available for execution here.

## 2026-11-19 follow-up audit (v0.4.3-dev)

- `START-WINDOWS.cmd` updates dependencies on every start, including an already-existing `.venv` (particularly Windows `tzdata`). Use `START-WINDOWS.cmd --self-check` to verify upgrades.
- On a healthy catalog startup, safely retry deletion-staging cleanup for profiles already removed from the DB. Staging for an existing profile is retained for recovery; unknown files and locked profiles are NOT erased. Deletion cannot be guaranteed immediately if Windows maintains a file lock. See Diagnostics.
- GUI startup with corrupt/newer SQLite now displays an error and advises `START-WINDOWS.cmd --doctor` instead of silently failing. Back up the data directory before attempting any repair.
- `extract_text` results are held in memory for at most 15 minutes, wiped when browser sessions stop, and removed with the profile. Automated extraction must be intentionally requested by a workflow step.
- Unsupported proxy hostnames, reused credentials from changed usernames and profile engine switches with attached extensions are rejected or cleaned up proactively. API responds with HTTP 503 when local storage is unavailable.
- Windows CI has an explicit existing-venv upgrade lane; browser compatibility tests remain a separate, actual-Chromium lane. **No EXE is built.** Passing tests does not establish GenLogin/Titan parity.

## Batch task history (development)

Batch Tasks executes one validated workflow on the selected group of profiles, up to six concurrently, recording per-profile results. Restarting the application restores the recent status history but **does not restart unfinished workflows**. If a browser action was in progress during a crash, the result will be `uncertain`. Check the website yourself before deciding whether to repeat that task. Queued tasks are marked cancelled after an interrupted process.

The SQLite journal stores IDs, statuses, times, and safe error *types*, never cookies, extracted page content, workflow text or passwords. Up to 100 finished batches are retained. Deleting a profile also purges any finished batch history that references it. History does not imply that web transactions are reversible or executed exactly once.

## Graph variables and text capture (development)

In the **Automation → Node graph** editor, add a `set_variable` node to store a temporary literal, or `capture_text` to read text from a page selector. Link it to an action node and use `{{variable_name}}` in string fields such as `fill.text` or selectors. All values live only for one workflow run, with at most 32 variables and 4,096 characters per value.

Example graph fragment (link the nodes sequentially between `start` and `end`):

```json
{
  "format": "AutumnGenLogin/graph-1",
  "nodes": [
    {"id":"start","type":"start"},
    {"id":"read","type":"capture_text","name":"headline","selector":"h1"},
    {"id":"fill","type":"action","step":{"action":"fill","selector":"#notes","text":"{{headline}}"}},
    {"id":"end","type":"end"}
  ],
  "edges": [
    {"from":"start","to":"read","branch":"next"},
    {"from":"read","to":"fill","branch":"next"},
    {"from":"fill","to":"end","branch":"next"}
  ]
}
```

Captured page text cannot be substituted into navigation URLs: this prevents accidental exfiltration of page content through `goto`. Literal-only variables can provide URL components; all expanded actions must pass validation again. The workflow does not store or show captured values in logs, the scheduler or batch history. No arbitrary Python/JavaScript execution is supported.
