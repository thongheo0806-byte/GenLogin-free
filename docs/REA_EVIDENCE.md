# REA evidence log: observed versus inferred

Method: followed [morluto/rea's `reverse-engineer-anything` skill](https://github.com/morluto/rea/blob/main/.agents/skills/reverse-engineer-anything/SKILL.md) for evidence-first classification. The skill itself is guidance; installing or reading it does **not** connect native inspection tools or provide permission to access proprietary software.

- **Observed:** Public GenLogin documentation covers profile groups, local/cloud, proxies, extensions and automation; linked in FEATURE_MATRIX.
- **Observed:** The target GitHub repository began empty, so this is a new independent codebase, not a patch to a previous project.
- **Not observed:** No GenLogin EXE, installer package, executable hash, live GUI session, memory dump, HTTP traffic capture or REA target Evidence ID was available.
- **Not claimed:** No assertion of proprietary GenLogin fingerprint algorithm, browser patches, internal API, anti-detection rates or byte-identical functionality.
- **Design choice:** Use Playwright-supported persistent Chrome/Edge browser contexts. The source implements the documented capabilities available from standard libraries, and marks unsupported capabilities clearly.

## If owner supplies a legal test installation later

1. Record exact GenLogin version, Windows version, package hash, license constraints and authorized test scope.
2. Compare observable workflows (create/edit/open/close profiles, proxy error states, export/import) from a clean test account, avoiding production account secrets.
3. If authorized to inspect the package, route the shipped binary through REA's artifact inventory appropriate to its actual type; retain evidence metadata and separate findings from hypotheses.
4. Record UI state transitions and reproducible failures. Capture only synthetic test data and redact credentials.
5. Build a feature-by-feature black-box comparison test, not a direct source or branded-artwork copy.
6. Validate Windows EXE in an actual interactive desktop session, not solely GitHub Actions self-check.
