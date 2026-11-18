# GenLogin feature matrix / AutumnGenLogin acceptance evidence

Assessed 2026-11-18 from public vendor descriptions, Microsoft Playwright documentation and audited application source. **This is not an observed GenLogin binary audit**. Product plan, version and behavior must be pinned before making a genuine equivalence claim.

| Capability | Public GenLogin source | AutumnGenLogin development state | Evidence / work remaining |
|---|---|---|---|
| Profile create/edit/delete/clone | https://docs.genlogin.com/group-profiles/create-profile/overview | Implemented | SQLite unit tests and manual GUI need verification |
| Group, tags, bulk launch | https://docs.genlogin.com/group-profiles/group-profiles | Implemented basic | No group hierarchy, bulk workflow orchestration |
| Local/cloud profiles | https://docs.genlogin.com/group-profiles/local-and-cloud-profiles | Local only | No cloud sync/backend/conflicts |
| Fingerprint / Titan core | https://docs.genlogin.com/group-profiles/create-profile/overview | **Not implemented** | Native engine details unknown, no proof of equivalence |
| Proxy and network settings | https://docs.genlogin.com/group-profiles/create-profile/network-and-webrtc | HTTP/SOCKS5 proxy metadata | No actual proxy integration/leak testing or complex routing |
| Extensions | https://docs.genlogin.com/group-profiles/extensions | Manual local Manifest V3 library with explicit opt-in for Chromium | Needs real browser extension run, gallery, policy, updates, security review |
| No-code automation | https://genlogin.com/automation | Sequential visual step editor (add, edit, reorder, delete) | Not full graph, variables/branches/loops, click-by-image or recorder |
| Advanced task operations | https://genlogin.com/automation | Parallel open and per-profile JSON actions | No scheduler, synchronizer, action recorder, video, miniapp design |
| External API | https://docs.genlogin.com/genlogin-api/profile-api/1.-profile-list | Local bearer-token API with different contract | API parity and SDK missing |
| Team access / sharing | https://docs.genlogin.com/group-profiles/share-profile | Not implemented | Requires identity, encryption and RBAC |
| Tests & diagnostics | internal product engineering requirement | Unit tests plus real Chromium integration test prepared | Windows CI result must be evaluated; GUI test not performed |

**Critical unknowns:** full GenLogin release/plan feature list, proprietary engine semantics, browser provenance, profile migration, runtime behavior, plugin support and licensing. The official marketing page lists scheduler, synchronizer, AI, headless, image click, recording and miniapps; a simple sequential builder is not equivalent to those features.
