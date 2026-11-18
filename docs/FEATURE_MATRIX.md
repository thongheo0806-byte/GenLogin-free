# Product evidence matrix

Date assessed: 2026-11-18. This inventory is based on publicly available documentation, not an inspected GenLogin binary or witnessed GenLogin desktop session. Feature names may differ between versions and plans.

| Public GenLogin capability | Evidence | AutumnGenLogin v0.2.0 | Gap / verification |
|---|---|---|---|
| Local and cloud profiles | https://docs.genlogin.com/group-profiles/local-and-cloud-profiles | Local profiles only | Cloud requires a new optional secure backend |
| Group profiles | https://docs.genlogin.com/group-profiles/group-profiles | Local group field/filter and bulk launch | Bulk actions and nesting future |
| Create browser profiles with language | https://docs.genlogin.com/group-profiles/create-profile/overview | Locale, user-agent, viewport, timezone | Full hardware, Canvas, WebGL fingerprint not provided |
| Network and WebRTC | https://docs.genlogin.com/group-profiles/create-profile/network-and-webrtc | Per-profile proxy | No verified WebRTC leak handling or advanced network fingerprints |
| Extensions | https://docs.genlogin.com/group-profiles/extensions | Not implemented | Add audited extension management UI |
| Workflow automation / group tasks | https://docs.genlogin.com/automation-guide/running-automation-separately-following-profile-group | JSON task steps per profile | No drag/drop, scheduler, repeat or orchestration UI |
| API for profiles | https://docs.genlogin.com/genlogin-api/profile-api/1.-profile-list | Different, authenticated local API | Deliberately no GenLogin API compatibility promise |
| Selenium / Puppeteer integrations | https://docs.genlogin.com/record-automation/selenium | Playwright integration internally | CDP integration and automation SDK future |

**Critical unknowns**: behavior of the installed GenLogin release, engine patches, actual fingerprint values, execution concurrency, authentication, failure handling, settings migrations, version-specific UX, browser patch licensing. A public feature description does not prove implementation fidelity.
