# AutumnGenLogin roadmap

## v0.1: foundation (code included)

- [x] Local SQLite profile inventory, CRUD, clone, groups, tags, search
- [x] Per-profile Playwright persistent context, Chrome/Edge channel
- [x] Proxy server and optional OS-protected credential
- [x] Workflow JSON validation/execution + screenshots
- [x] Browser-worker queue, local authenticated API
- [x] Source test suite + GitHub Actions build recipe
- [ ] Successful Windows release build and interactive UI/manual browser QA (**not yet verified**)

## v0.3: operational reliability (implemented)

- [x] Cross-process OS profile leases for browser launch and deletion
- [x] Offline SQLite integrity, write access, disk capacity, orphaned-data diagnostics
- [x] GUI Diagnostics button, JSON/CLI diagnostics and regression tests
- [ ] Interactive Windows browser/proxy failure testing still required

## v0.2: quality and browser operations

- [ ] Live browser smoke tests using installed Chrome/Edge on Windows
- [x] Offline launch/storage diagnosis; [ ] full interactive crash recovery
- [ ] Proxy validation and explicit WebRTC/DNS leak diagnostics (no guarantees)
- [ ] Extension install/disable management and profile templates
- [ ] Bulk create/edit/delete, advanced filtering, tag taxonomy and CSV import
- [ ] Persistent task queue, scheduler, retry policy and task result store
- [ ] Signed installer and versioned GitHub Release

## v0.3: visual automation

- [ ] Accessible drag-and-drop workflow graph with versioned JSON schema
- [ ] Recorder/editor for actions on user-owned websites, with confirmations
- [ ] Selector inspector, interactive debugging, breakpoints, screenshots, action history
- [ ] Workflow scheduling, controlled parallel execution and safe rate limits
- [ ] Playwright/CDP integration contracts for local developers

## v0.4: optional AI assistant and operational safeguards

- [ ] Local Ollama adapter (no paid API required), opt-in cloud model adapter
- [ ] Human approval before sensitive AI-proposed actions
- [ ] Per-domain allowlists, data redaction and preview mode
- [ ] Profile backup encryption and restore validation
- [ ] Optional encrypted team sync designed separately from local-only core

## Research-only, no functionality promised

- Deep browser fingerprint virtualization/custom Chromium patches: require separate research, browser-maintenance capacity, platform testing, supply-chain and licensing review. No promise of detection avoidance.
- GenLogin proprietary functionality: undocumented, may not be feasible, compatible or lawful to replicate exactly.
