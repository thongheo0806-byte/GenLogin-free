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
