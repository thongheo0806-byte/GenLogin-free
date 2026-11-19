# Optional encrypted team metadata sync (self-hosted)

AutumnGenLogin has no mandatory account or telemetry. Synchronization is **off by default** and does not upload browsing session data.

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
