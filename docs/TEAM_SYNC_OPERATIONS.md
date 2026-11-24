# Optional encrypted team metadata sync (self-hosted)

AutumnGenLogin has no mandatory account or telemetry. Synchronization is **off by default**. The regular metadata/workflow sync excludes browser session data; a separate, explicitly confirmed **manual encrypted `.aglb` backup handoff** can now transfer sensitive encrypted archives within strict size/role limits. See [manual session handoff](CLOUD_SESSION_HANDOFF.md). This is not automatic cloud session sync.

## Development local test

1. Install `requirements.txt` (includes `cryptography`).
2. In a separate process, start `python main.py --hub`. The hub listens **only** on `127.0.0.1:8899` by default. Override the port with `AUTUMN_HUB_PORT`.
3. In the desktop **Team sync** tab, use `http://127.0.0.1:8899`, register (password ≥12 characters), log in, create a team and save the team UUID.
4. Share an **encryption passphrase** (≥12 characters) with authorized members over a separate trusted channel; it never leaves the client. Create a second user and invite them via an owner/admin account.
5. Push and pull **profiles** or **workflows** manually. Conflict status HTTP 409 means the remote revision changed; pull/review before retrying. Pulling profiles merges allowlisted fields only and does not silently delete existing records or replace local proxy credentials.
6. Database: `%LOCALAPPDATA%\\AutumnGenLogin\\team-hub.sqlite3` when run on Windows. Back it up with SQLite's backup API (or after clean shutdown), not by copying a WAL-mode database file while it is open.

## Security boundaries

- **Never** bind the hub directly to public IPs. The Python server only permits loopback. A remote deployment must configure a maintained TLS reverse proxy, authentication/rate limiting, server backups, access logs without secrets and monitoring. The application enforces HTTPS for non-loopback client URLs.
- Passwords are salted and hashed using `hashlib.scrypt`. Bearer tokens are random, stored as hashes at the server, expire after 24 hours and remain in client process memory. TLS is mandatory beyond loopback.
- AES-256-GCM with scrypt-derived encryption key, fresh salt/nonce and authenticated format tag. Without the shared passphrase the server cannot recover plaintext. **There is no password recovery.**
- `safe_profile_metadata()` allows only: UUID, name, group, tags, browser type, start URL, locale, timezone and viewport. It excludes cookies, localStorage, browser folder, proxy host/port/username/password, extensions, API tokens, screenshots and automation results.
- Team roles: owner administers members, admin may manage editor/viewer roles but cannot demote the team owner or peer administrators; even the owner cannot be demoted through the membership endpoint, editor may update documents, viewer may only read. All permissions are checked server-side. Revision numbers protect against lost-update writes, not malicious remote administrators or compromised clients.
- No claim of end-to-end security against malicious installed browser extensions, an infected OS, weak shared passphrases or metadata inferred from team membership.

## Explicit limitations

This is a **self-hosted opt-in metadata collaboration service**, not a preconfigured hosted cloud platform. Push/pull is manual and not guaranteed available offline. No GenLogin cloud API compatibility, live session mirroring, automatic conflict merges, sync between browser-data directories or enterprise audit/compliance is claimed.

## Opt-in manual encrypted archive handoff (development)

The Team sync tab now includes explicit **Upload encrypted session backup** and **Download encrypted session backup** actions. These are separate from the metadata/workflows sync contract above: archive transfers are encrypted twice, uploaded in bounded 256 KiB chunks with an immutable final manifest and downloaded only to a new encrypted file. Team owners/editors may upload, viewers may download. Do not claim that the regular profile-metadata document now includes cookie/session data; it still strictly excludes that material. No automatic session transfer or remote browser folder synchronization exists. Review [CLOUD_SESSION_HANDOFF.md](CLOUD_SESSION_HANDOFF.md) before using sensitive data.

## Archive revocation security boundary (2026-11-22)

Owner/admin can use **Revoke team archive** to delete a published
encrypted .aglb handoff from TeamHub. Viewer/editor permissions are
insufficient. Server remembers a tombstone so the same UUID cannot be
re-uploaded. This is atomic at the SQLite storage layer and is tested
with real localhost HTTP requests. Deleting a Hub archive **does not
delete previously downloaded .aglb files or invalidate site cookies**.
Only services that issued those sessions can revoke them. See
[CLOUD_SESSION_HANDOFF.md](CLOUD_SESSION_HANDOFF.md).

## Hardened Hub quotas and archive discovery (2026-11-23)

- Hub request sockets have a short inactivity timeout to bound stalled headers and
  incomplete bodies. Protected POST/PUT endpoints authenticate before reading
  a request body. The hub remains loopback-only.
- The hub checks the JSON envelope keys, base64 encoding, and salt (16 bytes),
  nonce (12 bytes), and ciphertext lengths before persisting an encrypted
  document. **This cannot prove the ciphertext has a valid authentication tag**;
  only a client holding the passphrase can authenticate/decrypt it.
- Each uploader is limited to **256** session documents and **64 MiB** of stored
  encrypted JSON, in addition to the existing team-wide 2048-document limit.
  These quotas are defensive limits, not complete resource accounting for
  all teams, users, or database storage.
- Team owners and admins may list encrypted archive UUIDs using
  `GET /teams/{team_id}/sessions` or **List team archives (admin)** in the
  desktop Team sync tab. The listing reports complete/partial handoffs,
  document counts, stored bytes and uploader names when known. It contains
  no decryption keys, ciphertext or session contents.
- Select an archive, copy its UUID and use **Revoke team archive** to delete
  its server-side documents. Legacy archives from before the uploader-tracking
  migration display an unknown uploader. Tombstoning does not remove already
  downloaded copies or invalidate third-party sessions.

## 2026-11-23 revision conflict reconciliation (development)

- A local GUI push now reads the current team document revision **before** the
  update. It uses an approved prior pull as its per-server/team/document
  baseline. Unknown existing remote documents cannot be overwritten blindly.
- Profile metadata supports a bounded per-field three-way merge of the
  previous approved version, local allowed metadata and current remote allowed
  metadata. Concurrent edits to different fields can merge only after an
  explicit preview confirmation. Concurrent edits to the **same** field are
  reported as structural conflicts without including values in error messages.
  Profile absence never silently deletes local browser profiles.
- Graph/sequential workflows are atomic documents. Divergent edits on both
  sides are **not** merged automatically; the operator must inspect and
  resolve them manually.
- The encrypted hub retains its server-side compare-and-swap revision check.
  A race between preview and upload returns HTTP 409, never an automatic
  retry or an overwrite. Successful three-way uploads clear the GUI baseline;
  a fresh approved pull is required before another update so remote-only
  changes are not silently reverted by stale local metadata.
- The GUI `_cloud_action` now dispatches worker results via its Tk polling
  queue instead of invoking Tk functions from network threads.
- This remains opt-in **metadata sync**, not live cookies, browser session
  synchronization, conflict-free replicated data types, or automatic
  disaster recovery.

## 2026-11-23 fail-closed metadata Pull preview

- The desktop **Pull metadata** path now checks local edits just as Push does.
  With a trusted accepted baseline, it computes a three-way merge of local,
  baseline and remote. Without any shared baseline it imports only disjoint
  remote UUIDs or records already identical on both sides. Same-UUID
  divergences are **blocked**, not resolved by assuming the server wins.
- Existing local-only UUIDs are retained. Only genuinely new or changed
  metadata records are applied. Proxy details, OS vault secrets and active
  profile browser directories are never copied from the server.
- The preview is checked again **under the SQLite write transaction** before
  modification. A concurrent local edit during review triggers a rejection,
  leaving metadata unchanged. Do not interpret the review as authorization to
  overwrite later local changes.
- An accepted baseline stores the actual remote snapshot, not the locally
  merged snapshot. A subsequent Push can still reconcile independent edits.
  Signing in again clears remembered baselines, since a new authentication is
  not proof that the same account owns the old sync history.
- There is no automatic conflict resolver or cross-device replay queue.
  A conflict requires operator review and a new pull; previously downloaded
  sessions are not touched. Workflows still require explicit document-level
  review and are never merged field-by-field.

## 2026-11-23 nonblocking desktop cloud metadata processing

- The **Push metadata** snapshot and second local-consistency check run
  on a worker thread, not the Tk event loop. A local edit after the preview
  is rejected before an attempted server-side compare-and-swap upload.
- **Pull metadata** downloads, SQLite snapshot reading, structural
  three-way merge and the final `BEGIN IMMEDIATE` SQLite transaction all
  run on background workers. Tk only presents confirmation/status and
  updates its widgets after worker completion. The final store write still
  compares the approved local snapshot atomically with current metadata.
- The GUI drops responses for a changed logged-in Cloud client, team scope
  or accepted remote baseline, avoiding an unrelated reply updating the
  current team's baseline. No automatic retry, forced overwrite or replay.
- A Windows Tk heartbeat regression deliberately stalls cloud SQLite
  work and verifies the UI keeps dispatching callbacks. This does **not**
  establish complete DB/GUI load testing for very large profile catalogs.


## 2026-11-23 versioned Team Hub scrypt migration (development)

- All **new** encrypted team documents now carry a strictly validated
  `kdf: {name: "scrypt", log_n: 15, r: 8, p: 1}` header. The client
  derives the AES-256-GCM key with `N=32768` and **authenticates the
  canonical KDF header** as associated data. Changing the claimed work
  factor or algorithm makes decryption fail. The hub validates envelope
  shape and bounds but **cannot** authenticate its ciphertext without
  the user's passphrase.
- Historic `AutumnGenLogin/encrypted-1` blobs without a `kdf` field
  remain decryptable using their original `N=16384` and historic AAD.
  An operator need not lose access to old encrypted revisions. An older
  un-upgraded client may, however, reject newly generated versioned
  envelopes; coordinate client upgrades with team members **before**
  publishing a new revision. No on-server mass re-encryption is performed.
- New Hub account registrations use `N=32768`. Existing user rows
  gain an additive `password_kdf_log_n` column defaulting to 14; only
  a successful login transparently upgrades that individual password
  hash to 15 using a fresh random salt. Username, user ID, team
  membership and other team data remain unchanged. A failed login does
  not trigger a hash change.
- Derivation work factors are bounded to `14..17` and `r=8,p=1`,
  with an explicit 256 MiB scrypt memory ceiling to reject malicious
  requests for huge resources. New registration uses 15; acceptance for
  larger values, full host load tests and independent security audit
  remain outstanding. The separate local `.aglb` profile backup has
  its **own** versioned KDF policy; this change does not rewrite it.


## Authentication resource bounds (2026-11-24)

Unknown usernames and known current-factor users with an incorrect password
perform one current-cost scrypt derivation and return the same 401 response.
Legacy N=16384 accounts perform two legacy derivations to approximate current
work. This is timing-leak mitigation, not proof of constant-time HTTP
responses; SQLite caching, old work factors and network effects can differ.
Registration still reports duplicate usernames (409).

At most four concurrent account-authentication KDF operations per process are
admitted across login, registration and successful legacy-hash upgrades.
Saturation returns 503 immediately, releasing slots on exceptions. Hash
upgrades derive the new hash before obtaining the SQLite write lock.
This bounds concurrent authentication KDF memory, not all HTTP request
threads or the total server memory. Production reverse proxies must enforce
connection limits, request-size limits and login rate limits; do not expose
the loopback development hub directly to the internet.
