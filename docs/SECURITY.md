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
- The GitHub Actions self-check covers packaged module import and local DB, **not** an interactive browser launch or platform leak audit.
- No cloud data loss recovery, sync encryption, automated secret backups or security certification.
- There is no password to open the main app. Anyone with access to the logged-in Windows session may operate its profiles.

## v0.3 operational safeguards

- Each browser profile now obtains an OS-backed, non-blocking lock before opening a persistent user-data directory. Deletion attempts acquire the same lock; they are refused while the profile is in use. Lock files persist intentionally to avoid unlink/recreate races.
- Diagnostics use local SQLite `PRAGMA quick_check`, write-access checks and orphan-directory reporting. They do not request websites or read browser cookies/history. The tool never deletes suspected orphan data.
- Run `python main.py --doctor` or `python main.py --doctor-json` for a local, offline report; GUI has a **Diagnostics** button. Reports contain no proxy usernames or passwords.
- This prototype is not an anonymity suite and does not bypass Sybil, anti-bot, CAPTCHA, KYC or terms-of-service enforcement. No such outcome can be guaranteed.
