# Security / privacy model

## Trust boundaries

- Desktop UI and browser subprocesses run under the current Windows user.
- Database and Chromium browser data are local to that user. Browser data contains cookies, history and tokens, so treat the entire local folder as confidential.
- Proxy passwords are stored by the OS keyring (Windows Credential Manager). Passwords must not appear in SQLite or metadata exports. Do not share keys from the credential store.
- Local API is **disabled by default** and listens on `127.0.0.1` only. A randomly generated token is required on every endpoint, including health check. Avoid copying tokens into public logs. API is not a security boundary against local malware running as the same user.
- Workflow actions intentionally omit arbitrary script execution and reject non-http(s) navigation URLs. They can still interact with untrusted websites and sensitive account sessions, so only run trusted workflows.
- Screenshots and extracted text may contain secrets; guard the export location. No telemetry code is included.
- Dependency builds must be reviewed for supply chain risk. Pins are version ranges for the prototype; a reproducible production release requires lock files, binary signing and artifact provenance.

## Explicit limitations

- Browser identity settings do not imply fingerprint anonymity or prevent correlating accounts.
- The GitHub Actions self-check covers module import and local DB; browser integration checks are distinct and do **not** establish platform leak auditing.
- No cloud data loss recovery, sync encryption, automated secret backups or security certification.
- There is no password to open the main app. Anyone with access to the logged-in Windows session may operate its profiles.

## v0.3 operational safeguards

- Each browser profile now obtains an OS-backed, non-blocking lock before opening a persistent user-data directory. Deletion attempts acquire the same lock; they are refused while the profile is in use. Lock files persist intentionally to avoid unlink/recreate races.
- Diagnostics use local SQLite `PRAGMA quick_check`, write-access checks and orphan-directory reporting. They do not request websites or read browser cookies/history. The tool never deletes suspected orphan data.
- Run `python main.py --doctor` or `python main.py --doctor-json` for a local, offline report; GUI has a **Diagnostics** button. Reports contain no proxy usernames or passwords.
- This prototype is not an anonymity suite and does not bypass Sybil, anti-bot, CAPTCHA, KYC or terms-of-service enforcement. No such outcome can be guaranteed.

## Development hardening, 2026-11-18

- Extension ZIP imports reject traversal paths, symlinks, oversized entries and malformed Manifest V3 metadata. Imported code is **not** executed during install. An explicit permission confirmation is required before attachment and profile restart.
- The extension permission preview is informational, not a code review. Only install source from a trusted developer. Running arbitrary extensions can expose browser sessions.
- `extract_text` workflow logs only the text length, not site content, to reduce secret exposure.
- The automated Windows CI runs synthetic local web pages with no real accounts. This does not prove Titan-style fingerprinting or Sybil resistance.
- No EXE is produced until the documented release gates are met.

## 2026-11-19 audit remediation (development only)

- `--doctor` / `--doctor-json` read metadata without creating a missing database, even when the normal app would fail initialization. `Path.as_uri()` avoids misparsing `#`, `?` and `%` in folder names. The disk-writability check uses and immediately closes a temporary file, not the SQLite database.
- Browser workers periodically pump Playwright events and observe `BrowserContext` close instead of waiting indefinitely on the command queue. A real-`BrowserManager` Chromium CI test was added; manual-close behavior is additionally tested using a deterministic stub.
- Deletion uses same-volume staging moves, database transaction and best-effort post-commit cleanup. Failure before commit restores original browsing directories; failed cleanup after commit is reported in diagnostics as quarantined data. Credentials are removed only after the metadata delete succeeds.
- Credential editing follows a compensating transaction: database first, OS vault second; a vault error triggers metadata restoration. OS vault + SQLite cannot provide atomic transactions across both stores.
- `extract_text` output is bounded and available from the authenticated local API in process memory. Those values may contain account secrets or sensitive content; never log them or expose the token.
- Chromium's documented SOCKS5 proxy implementation does **not** support username/password authentication (see https://chromium.googlesource.com/chromium/src/+/main/net/docs/proxy.md). Authenticated SOCKS5 settings are rejected rather than advertised as supported.
- SQLite `user_version=1` is now recorded. This is the baseline for future migrations, **not** a complete migration suite.
