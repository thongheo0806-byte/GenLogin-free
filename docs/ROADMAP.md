# Roadmap (release held pending verified feature parity)

## Current development implementation

- Local profile CRUD, clone, groups/tags, proxy settings, credential vault, metadata import/export, process locks.
- Standard Chrome/Edge/Chromium persistent contexts via Playwright. Manual local Manifest V3 extension packages for bundled Chromium only.
- Strict sequential JSON automation and an accessible basic visual step editor; token-authenticated loopback control API.
- Tests for SQLite, API, locks, validation, extension upload security and visual-step definitions; real-browser CI integration test separated from unit tests.
- Windows Actions now tests without packaging a release binary.

## Work before release

1. Audit actual GenLogin/Titan binaries only when legal rights, version and instrumentation are provided. Create witnessed behavior/evidence matrix.
2. Complete profile management: editable view columns, sorting, secure import/export policy, safe profile backups and migrations, proxy tester, browser version manager.
3. Implement extension permission change review, updates, rollback and actual cross-version compatibility tests.
4. Implement a graph-based workflow engine, recorder, variables, loops, branches, task scheduler, structured results and controlled execution.
5. Implement team/cloud only with explicit opt-in and a separately audited authenticated backend and encryption.
6. Pass real Windows GUI tests, Chromium/Chrome/Edge e2e tests, failure injection, license review, packaging SBOM and acceptance criteria.
7. Only then reintroduce the Windows EXE build workflow with approvals and reproducibility attestations.

See `RELEASE_GATES.md` for the actual acceptance contract.
