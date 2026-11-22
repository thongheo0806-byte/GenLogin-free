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

## 2026-11-21 executable evidence intake (NOT a Titan comparison)

This repository now offers a small, fully offline **evidence intake validator** at `autumn_genlogin/titan_evidence.py`. It reads **only** a user-prepared JSON record containing a pinned GenLogin/Titan release and authorized local installer SHA-256, provenance, Windows edition, legal and observation authorization, plus named synthetic behavioral comparison cases with each side's artifact SHA-256. The exact input schema has a blank starting template in `examples/titan/reference-evidence-template.json`.

Run from the project root:

```powershell
python -m autumn_genlogin.titan_evidence examples/titan/reference-evidence-template.json
```

The template has no actual Titan binary, test actions or authorized observations; the tool returns **`state=blocked` and exit code 1**. A malformed file returns exit code 2. Even a user-constructed JSON file in which every field reports success can yield at most `needs-independent-human-review` and **`can_build_exe=false`, `can_claim_titan_parity=false`**. A parser cannot verify source authenticity, independent witness identity, the terms of a vendor license or the proprietary browser's actual behavior. The program never downloads, launches, patches, decompiles or instruments Titan.

Required 12 cross-product synthetic comparison areas: profile lifecycle, session persistence, network/proxy consistency, browser locale/timezone, extension behavior, recorder, scheduler recovery, GUI accessibility, cloud-profile transfer, rendering consistency on a controlled page, long-run reliability, and license/distribution review. Every untested/failed case remains an explicit blocker. The test harness must never use personal login accounts or infer anti-fraud evasion from browser rendering.

The public release notes page currently lists **GenLogin 4.5.1 (06/08/2026)** as the latest entry. This is **not** an inspected installer: no binary hash, installed edition, license, actual Titan rendering or parity report has been verified. A legally obtained reference and controlled human observations are independent prerequisites. See `TITAN_EVIDENCE_INTAKE.md` for instructions and the precise remaining release blocker.

## Evidence-intake implementation, 2026-11-22 (non-invasive)

The new `autumn_genlogin.titan_evidence` module **does not inspect, execute,
download, patch, copy or reverse engineer Titan**. It accepts only a small,
strictly validated JSON evidence index and reports the gaps remaining before
a lawful, reproducible Windows comparison. This is an evidence-*readiness*
check, **not a feature or parity certificate**.

Start with `examples/titan/reference-evidence-template.json`. Keep
`reference: null` and `cases: []` until independent authorized observations
and exact, legally sourced binaries actually exist. Do not fabricate hashes,
release editions or witness reports.

```powershell
python -m autumn_genlogin.titan_evidence examples/titan/reference-evidence-template.json
```

The command exits with status **1** while evidence remains unverified.
Even a syntactically complete, self-reported 12/12 pass is categorized
`needs-independent-human-review`, never `can_claim_titan_parity` or
`can_build_exe`. The CI verifies that this guard remains enforced and that
the reference template is honestly incomplete.

A valid evidence reference requires vendor/product, exact version,
edition, Windows version, installer SHA-256, official provenance,
documented legal/observation authorization and an inspection date.
Each comparison case requires separate pass/fail/not-run statuses
and artifact digests for the reference and AutumnGenLogin. No artifact
contents are uploaded to the repository, no credentials or session data
belong in the JSON, and SHA-256 strings alone do **not** establish authenticity.

The 12 cases are profile lifecycle, session persistence, proxy consistency,
locale/timezone, extension behavior, recorder, scheduler recovery, GUI
accessibility, cloud-profile transfer, rendering consistency, long-run
reliability and distribution licensing. Any missing/failed case blocks
further readiness; external signed witness, licensing, reproducibility,
security, packaging and all other `RELEASE_GATES.md` checks remain mandatory.
