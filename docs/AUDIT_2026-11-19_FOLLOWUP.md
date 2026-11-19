# Audit follow-up, 2026-11-19

Status: source fixes prepared for review; no EXE build authorized.

Scope: startup upgrade path; bounded deletion-staging retry guarded by per-profile OS lease and catalog check; corrupt DB GUI error dialog; private workflow-result expiry and cleanup; typed Playwright `TargetClosedError`; stricter proxy host/locale validation; proxy credential revocation; Chrome/Edge extension compatibility check; API 503 handling.

Residual risk: a crash between moving browser data into staging and committing metadata can leave staging with a still-present profile. This is intentionally NOT erased: requires user-mediated recovery. A Windows file lock can delay deletion beyond one restart; diagnostics must continue to report it.

No GenLogin/Titan feature-parity claim or Sybil immunity is supported.
