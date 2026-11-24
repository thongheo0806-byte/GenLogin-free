# Incremental refactor acceptance (2026-11-24)

This is the source/behavior inventory for the refactor sequence. A branch
is not an accepted release until its CI and combined main CI pass.

| Step | Scope and regression contract |
|---|---|
| #62 | Retired legacy sync manager; six behaviors migrated, no obsolete imports, original direct Playwright persistence/extension tests retained |
| #63 | Desktop Store and independent Hub immediate writer contexts; commit/rollback, writer-reservation, idle-read, concurrent claim/revision tests; Ruff import rules on locks.py |
| #64 | Frozen pre-refactor action validator/fields/recordability differential oracle; 13 declared actions, strict field and context restrictions |
| #65 | All 17 local API GET/POST endpoints checked by identical golden loopback tests before and after route-table conversion |
| #66 | QA sync and Miniapps controllers; public workflow-draft bridge used by Miniapps and Cloud |
| #67 | Backup and Extensions controllers; preserved consent, review, leases and selected-profile bridge |
| #68 | Profiles controller and ProfileEditor, shared theme, public group snapshot for Batch, App file below 600 lines (enforced in test) |

The target is modularity and preserved behavior, not new production
capabilities. The old `transaction()` remains for compatible operations;
explicit writer reservations use `write_transaction()`. Ruff scope is
currently locks.py, not the entire repository. Structural mixin tests do
not establish that every remaining catalog or filesystem operation is
nonblocking. Full recorder cross-session semantics, general browser-use
agent, comprehensive Windows accessibility/stress and vendor parity are
not established by these refactors. **HOLD EXE BUILD** remains.

Real bounded Ollama planner runtime proof: run 45315092902, 3/3 synthetic
Chromium choices verified; not general-purpose browser-use acceptance.
