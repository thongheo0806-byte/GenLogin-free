# Local Miniapps catalog: reviewed JSON templates only

**Development status. Not a remote app store, not signed plugins, and not GenLogin MiniApps parity.**
EXE packaging remains HOLD.

## User journey

1. Open **Miniapps → Import JSON**, select a *trusted* local `.json`
   file complying with `AutumnGenLogin/miniapp-1`.
2. The application checks that the manifest has only `format`, `name`,
   `version`, `description`, `category`, `workflow`. Each action must
   already be supported by AutumnGenLogin's verified JSON workflow engine.
3. Use **Preview** to inspect the declared description, navigation origins,
   step count and action names. Imported packages are not executable.
4. **Load draft** requires explicit confirmation and replaces the
   current Visual Builder's editable draft, not any browser state.
   Review the full JSON selectors, local image assets, placeholder fields,
   navigation targets and website terms before choosing **Run** separately.
5. Remove catalog entries independently of workflow files the user exported.

## Data and security contract

- 64 KiB max package, up to 50 typed workflow steps and 100 local catalog
  entries; a single name/version has one immutable SHA-256 package ID.
- SQLite keeps local canonical JSON, no network connection on import,
  no arbitrary code, extension binaries or external install command.
- `fill` may not carry a non-empty text field; `select_option` must be
  `REVIEW_OPTION`; URLs with query/fragment are rejected to reduce
  accidental credential leakage.
- Miniapp navigation requires HTTPS or `http://127.0.0.1:port`
  for self-owned local QA pages. A declared HTTPS origin **does not**
  grant authorization to automate that site or follow links to others.
- A SHA-256 content digest detects accidental catalog tampering; it does
  **not** establish developer identity, malicious-intent review or a
  cryptographic publisher signature.
- Browser sessions, cookies, password vault values, API bearer tokens,
  user-data directories and extracted text are never included in imported
  miniapp manifests.
- The local catalog is not automatically shared with the team hub,
  shipped to any cloud endpoint or downloaded from GitHub.

## Missing features / acceptance

There is **no** online discovery, app ratings, publisher signing,
revocation, automatic updates, nested subworkflows, per-app permissions
enforced by network interception, third-party plugin code or GenLogin
MiniApps ABI compatibility. A complete marketplace will require a
publisher trust and update model, dependency licensing, sandboxing,
user consent, checksum pinning, rollback and independent Windows QA.

`tests/test_miniapps.py` covers manifest/schema rejection, tampering,
import limits, conflicting updates and persistent catalog. Tkinter CI
smoke checks Miniapps tab rendering with a synthetic entry. No external
website is visited as part of these tests.
