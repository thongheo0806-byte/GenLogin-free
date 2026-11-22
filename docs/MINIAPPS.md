# Local Miniapps catalog: reviewed JSON templates only

**Development status. Supports manually pinned Ed25519 signed JSON templates, but NOT a remote app store, third-party code plugins, or GenLogin MiniApps parity.**
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

There is **no** online discovery, app ratings, verified real-world publisher identity, centralized key revocation, automatic updates, nested subworkflows, per-app permissions
enforced by network interception, third-party plugin code or GenLogin
MiniApps ABI compatibility. A complete marketplace will require a
publisher trust and update model, dependency licensing, sandboxing,
user consent, checksum pinning, rollback and independent Windows QA.

`tests/test_miniapps.py` covers manifest/schema rejection, tampering,
import limits, conflicting updates and persistent catalog. Tkinter CI
smoke checks Miniapps tab rendering with a synthetic entry. No external
website is visited as part of these tests.


## Optional cryptographic publisher-key continuity (2026-11-22)

Miniapps now support two local file formats:

- `AutumnGenLogin/miniapp-1`: existing **UNSIGNED** JSON templates. Still
  manually importable and editable after the original explicit review.
- `AutumnGenLogin/signed-miniapp-1`: exact envelope fields
  `format`, `manifest`, `public_key` (canonical base64 of 32 raw
  Ed25519 bytes), and `signature` (canonical base64 of 64 Ed25519 bytes).
  Its domain-separated signature covers a canonically encoded, validated
  workflow manifest, not arbitrary third-party program code.

The new **Trust publisher key** action accepts a public key and local label.
It shows the SHA-256 key fingerprint for **out-of-band verification** before
the user consents. Import of a signed package whose exact key is not trusted,
whose signature fails, or whose name has been previously pinned to another
key is rejected atomically. The GUI displays **trusted**, **unsigned** or
**untrusted** on every row; a package signed by a revoked local key cannot
be loaded even through the library's `get` method.

**Important:** A digital signature does not certify that a developer is
reputable, legally authorized or that a workflow is safe. The publisher
could deliberately sign a harmful selector/action. A local SHA-256 key
fingerprint is not an independent certificate of the publisher's identity.
Never trust a new key solely because it appears inside a signed package.
There is no online trust/revocation authority, signed Web Store package
format, automatic upgrades, code-based miniapps or Titan equivalence.

### Developer signing helper (manual and local)

With OpenSSL installed, generate a private signing key **outside your
Git repository and cloud-synchronized folders**:

```powershell
openssl genpkey -algorithm ED25519 -out C:\private\miniapp-publisher.pem
python -m autumn_genlogin.miniapp_signatures public C:\private\miniapp-publisher.pem
python -m autumn_genlogin.miniapp_signatures sign examples/miniapps/inspect-example-com.json C:\private\miniapp-publisher.pem inspect-signed.json
```

The `public` operation prints only the raw public key and its fingerprint.
Share the public key and fingerprint through separate, trusted channels.
Never publish or upload your private PEM. `sign` writes a NEW signed JSON
file with exclusive creation and refuses to overwrite an existing file.
A user manually trusts the public key in Miniapps before selecting **Import
JSON** for the signed package. Import itself never launches a browser.

Existing SQLite catalog rows remain compatible: only two additive tables,
`miniapp_publishers` and `miniapp_attestations`, are created. Removing
a trusted key leaves previously imported signed templates visible, marked
`untrusted`, but blocks loading them until the exact key is trusted again.
Deleting a Miniapp removes its signature attestation; private signing
keys are NEVER stored in the application's SQLite database.
