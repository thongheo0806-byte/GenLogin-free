# GenLogin and Titan: public-evidence feature assessment

Assessed 2026-11-18. **This is public documentation research, not decompilation or an empirical test of Titan.** The `morluto/rea` skill was consulted for its evidence/unknowns separation. There is currently no original GenLogin installer, runtime trace, REA MCP provider, or binary Evidence ID in this project.

## Publicly documented scope

| Function | Public source | AutumnGenLogin implementation / boundary |
|---|---|---|
| Local and cloud profiles | https://docs.genlogin.com/group-profiles/local-and-cloud-profiles | Local SQLite only; cloud has no implementation |
| Group profiles | https://docs.genlogin.com/group-profiles/group-profiles | Groups, filtering and group launch; no RBAC |
| Browser identity settings and Titan | https://docs.genlogin.com/group-profiles/create-profile/overview | Stock Playwright Chrome/Edge/Chromium; **no Titan-like custom engine** |
| Proxy and WebRTC controls | https://docs.genlogin.com/group-profiles/create-profile/network-and-webrtc | Proxy options; no verified WebRTC/DNS leak controls |
| Extensions | https://docs.genlogin.com/group-profiles/extensions | Not implemented |
| Visual workflow automation | https://genlogin.com/automation | Validated JSON workflow, no visual graph/recorder |
| API / third-party automation | https://docs.genlogin.com/genlogin-api/profile-api/1.-profile-list and https://docs.genlogin.com/record-automation/selenium | Own token-authenticated loopback API; no API parity |
| Team collaboration | https://genlogin.com/management | Not implemented |

The official release notes describe continuing changes to Titan and automation: https://genlogin.com/release-notes. No internal algorithms, source patches, exact test coverage, or legal permission to copy an engine are implied by those marketing claims.

## Open-source research considered

- [REA reverse-engineer-anything](https://github.com/morluto/rea/blob/main/.agents/skills/reverse-engineer-anything/SKILL.md): evidence-first analysis and explicit unknowns. Reading the skill does **not** install its runtime or inspect an application.
- [Microsoft Playwright persistent profiles](https://github.com/microsoft/playwright.dev/blob/main/mcp/configuration/user-profile.mdx): documented browser-state persistence and isolation; this does not constitute anti-fingerprint technology.
- [BrowserOpsLab/playwright-browser-profile-manager](https://github.com/BrowserOpsLab/playwright-browser-profile-manager): example of local browser profile management, explicitly without security-control bypass. No third-party code copied.

Before reusing any external code: review the exact license, provenance, vulnerabilities, update process and functionality. A GitHub repository being public does not mean its packaged browser engine is open-source or free to redistribute.

## Sybil evaluation boundary

Sybil decisions are made by platforms, not browsers. One-person-one-account rules, transaction links, coordinated behavior, account ownership, KYC and platform terms may be involved. It is impossible to guarantee a browser will never be flagged. AutumnGenLogin will not claim immunity, emulate unrelated people to defeat Sybil controls, or bypass service anti-abuse systems.

Legitimate product quality priorities: reproducible browser versions, stable per-profile storage, cross-process locks, secure credential handling, optional privacy diagnostics, safe automation and regression testing against sites owned or authorized by the operator.

## Evidence required for any later compatibility statement

- Obtain an authorized GenLogin installer; record vendor license, version, SHA-256 and provenance.
- Document user-visible tasks with synthetic accounts and no production cookies or secrets.
- If licensing and authorization permit, run REA on that exact executable, retain the inspection Evidence record and separately verify observations using independent tests.
- Compare functional behavior in a test matrix. Never describe an inferred architecture as an observed implementation.
- Validate AutumnGenLogin in a fresh Windows VM with installed Chrome/Edge, actual GUI interactions, process termination/recovery, profile migration and proxy failure scenarios.

## Current deliverable

AutumnGenLogin v0.3 adds cross-process profile locks and offline diagnostic reporting. This improves reliability but does not change fingerprint behavior or claim GenLogin/Titan parity.
