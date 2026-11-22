# Manual encrypted session backup handoff through TeamHub

**Development-only. Not full cloud browser-session sync.**
EXE release remains HOLD; see [release gates](RELEASE_GATES.md).

This is an opt-in file courier for an **already encrypted**, stopped-profile
AutumnGenLogin `.aglb` backup. It is not live syncing a browser user data
directory, not shared browser execution, not an account session exporter in
plaintext and not a GenLogin-compatible cloud profile format.

## Manual user flow

1. Stop the source browser and use **Encrypted backup** in the main GUI to
   export a `.aglb` file with a strong, private *archive passphrase*. The
   file may contain cookies, localStorage, logged-in sessions, and personal
   information; treat it as a sensitive credential archive.
2. Start the opt-in TeamHub (`python main.py --hub` for local QA), login to
   a team and enter a separate strong *TEAM encryption passphrase*. The
   hub binds only loopback; remote access needs an independently audited
   HTTPS reverse proxy.
3. An owner/editor explicitly clicks **Upload encrypted session backup**
   and chooses a **stopped-profile** `.aglb` file. Confirm the sensitive
   upload. Only its encrypted bytes leave the client. The service stores
   chunks encrypted again with the team passphrase; a session manifest is
   published only after all parts are acknowledged.
4. The UI displays a transfer ID (UUID). Share this ID only with trusted
   team members through a separate channel, not in public messages.
5. A viewer or higher explicitly chooses **Download encrypted session
   backup**, supplies that ID and the same team passphrase, and saves to
   a **new** local `.aglb` file. Every chunk is authenticated during team
   decryption and the complete assembled archive is verified by SHA-256,
   exact length and file magic before being written.
6. The recipient separately chooses **Restore backup**, supplies the
   *original archive passphrase*, and restores to a **new local profile
   UUID**. Existing profiles are never overwritten. Original extension
   packages, proxy credentials and vault secrets are not transferred.

## Bounds and technical guarantees

- Archive maximum **16 MiB**, split into ≤64 *256 KiB* chunks. Larger profiles
  must use local offline backup or an independently validated storage
  design. A network failure may leave encrypted orphaned parts, but no
  published manifest; there is **no automatic retry**.
- Session documents use unique names `session-<uuid>-NN` and a final
  `session-<uuid>-manifest`. TeamHub rejects attempts to replace a
  published part or manifest, only permits owner/admin/editor to write,
  and caps encrypted session documents to 2048 per team.
- All parts and manifest are enveloped with AES-256-GCM and an independent
  random nonce/salt and scrypt-derived team key. The inner `.aglb`
  archive remains AES-GCM encrypted with the original archive key.
  The untrusted server never needs either passphrase.
- Download does **not decrypt the inner archive**, touch Chrome folders,
  run workflows, export passwords or install into an open browser.
  A compromised team member with both passphrases can still recover the
  sensitive browser session contents.
- Only documented, normalized manual operations with bearer-token
  authentication are allowed. No public HTTP binding; application enforces
  HTTPS for non-loopback service addresses.
- Integration tests on a real loopback HTTP hub verify owner/editor
  vs viewer RBAC, multi-chunk roundtrip, manifest immutability,
  tampering/incomplete upload detection, no plaintext in server SQLite,
  wrong passphrase rejection, no-overwrite and new-UUID offline restore.

## Not implemented or audited

**No automatic cloud session sync** (live file locks, cache consistency,
cross-version migration, browser sharing, conflict merges, cron replay,
unlimited blob storage, filesystem streaming, resumable uploads, orphan GC,
expiry/revocation, production secret rotation, backups/DR, bandwidth quotas,
full transfer protocol fuzzing, TLS infrastructure, verified engine
portability or legal Titan parity). A compromised OS, weak passphrases or
malicious extensions can defeat confidentiality.

Use the opt-in local self-hosted service only for synthetic profile test
data until production security and disaster recovery gates are satisfied.

## 2026-11-22 manual Hub archive revocation

The Team Sync tab now offers **Revoke team archive**. An authenticated
team **owner or admin** can enter a 36-character handoff UUID and explicitly
confirm permanent removal of that archive's encrypted chunks and
manifest from the self-hosted TeamHub. Editors and viewers are denied.

Revocation is one SQLite `BEGIN IMMEDIATE` transaction: it stores a
permanent `revoked_sessions` tombstone and deletes all ciphertext
documents under that UUID. The same transaction prevents races with
concurrent chunk publishers, and subsequent attempts to read or
republish any chunk/manifest using the old ID return HTTP 410. A
repeated revoke is idempotent and removes zero additional documents.
The tombstone contains only the team UUID, handoff UUID and timestamp,
not cookie data, URLs or passphrases.

**Critical limit:** any encrypted backup already downloaded to a
recipient's computer remains in their possession. Server-side
revocation cannot delete those copies, log out their accounts, invalidate
website cookies or revoke the underlying browser sessions. Invalidate
sessions at the **original services** if account access is compromised.
This is server-storage access control, not complete cloud session sync.
