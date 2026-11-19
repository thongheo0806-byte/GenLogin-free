# Evidence requirements for a Titan / GenLogin engine comparison

**Not completed.** GenLogin's Titan Browser is proprietary. The public marketing descriptions and REA skill instructions do not provide the engine source code, its ABI or legal authorization to copy protected components.

For a legally and technically defensible comparison, a tester needs:

1. Exact GenLogin/Titan release/edition and legal installation source, file hashes, date and distribution terms.
2. Written authorization where reverse engineering beyond normal observation is required. No extraction of secrets, license bypass, patching anti-tamper mechanisms or redistribution of protected binaries.
3. Reproducible Windows test VMs and benign local pages for: profile lifecycle, persistence, proxy DNS/auth compatibility, language and timezone, browser downloads, extension behavior, rendering differences and crash recovery.
4. Same test actions across Autumn/Playwright Chrome/Edge/Firefox/WebKit and a legally operated GenLogin baseline, with full pass/fail matrices, browser versions and run artifacts. Never infer parity from matched user-agent strings.
5. Resource, stability, accessibility, data-loss and packaging tests for each browser engine, not only Chromium headless or synthetic mocks.
6. Re-evaluate behavior after engine updates; isolate changes in third-party code and honor licenses.

`morluto/rea` documents inspection tools for **user-supplied binaries**, but does not install/register its MCP or provide a GenLogin binary by itself. At this time no REA binary analysis or direct Titan comparison has been run, and its proprietary features are **not** considered implemented.

Sybil is a policy/identity/linkage judgment made by external systems. No software can honestly guarantee it is never flagged. The project will not implement targeted anti-fraud evasion or claim immunity.
