# Titan / GenLogin evidence intake: release HOLD

**This is not proof of Titan equivalence.** The public GenLogin site
lists release 4.5.1 (2026-08-06), but AutumnGenLogin developers have
**not** received or inspected an exact authorized installer.

## What this repository can check today

Run a purely offline intake check against a JSON evidence file:

```powershell
python -m autumn_genlogin.titan_evidence examples/titan/reference-evidence-template.json
```

The template is deliberately empty. The expected result is
`{"state":"blocked","can_build_exe":false, ...}` with exit code 1.
The parser rejects unexpected input fields, duplicate evidence cases,
invalid SHA-256 artifacts, unsupported comparator types, unsupported
reference vendors and missing releases. It never downloads or executes
a proprietary GenLogin/Titan executable.

## Evidence an authorized human reviewer must collect

- Installer obtained from an official and permitted source with
  the pinned exact GenLogin version, edition and SHA-256 hash,
  legal license/provenance and separate observation authorization.
- Reproducible Windows 10/11 VM setup, documented isolated/test accounts,
  synthetic localhost pages, no live personal credentials and no
  attempts to defeat any platform's fraud/abuse controls.
- Paired independent observations for each required feature:
  profile lifecycle, reopen persistence, network/proxy behavior,
  timezone/locale, extensions, recorder, scheduler recovery,
  GUI accessibility, bounded cloud transfer, rendering consistency,
  long-running reliability and licensing/distribution.
- Artifacts captured and **retained by the authorized reviewer**,
  with SHA-256 hashes for baseline and AutumnGenLogin.
  The intake file contains hashes and outcomes only, not screenshots,
  cookies, logins, license tokens or vendor binary bytes.
- Independent inspection of witness authenticity, matching reference
  versions, valid setup, error handling, privacy controls and full
  release gates. A JSON field that merely says `pass` is not evidence
  a behavior actually occurred.

## Status values

- **blocked**: no pinned legally authorized reference, failed/unknown
  feature case, missing artifact digest or malformed evidence.
- **needs-independent-human-review**: every reported case is asserted
  as passed with all declared reference fields. This is a review
  queue, *not* a parity certificate.
- There is deliberately **no automatic released/certified status**.
  The code always returns `can_build_exe=false` and
  `can_claim_titan_parity=false`. Releasing a Windows EXE requires a
  separate authorized engineering and legal acceptance decision,
  plus the independent [RELEASE_GATES](RELEASE_GATES.md).

## Trust and legal restrictions

Do not extract protected code, inspect protected implementation internals
without authorization, bypass licensing/anti-tamper, redistribute vendor
binaries, or probe third-party anti-fraud classifiers. Test only
publicly exposed, legally permitted UI behavior with artificial data.

Feature-scope inspiration from public GenLogin release notes is not
a same-version differential runtime test. A Playwright browser displaying
similar pages does not become Titan.
