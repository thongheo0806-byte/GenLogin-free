# Browser engine compatibility and licensing

## Observed implementation

AutumnGenLogin uses Python Playwright persistent Chromium browser contexts and can launch installed Chrome/Edge, or Playwright-managed Chromium. It **does not** modify Chromium internals or Titan binaries. These are standard browser controls, not equivalent to an antidetect engine.

## Reliable references

- [Microsoft Playwright browser types](https://playwright.dev/docs/api/class-browsertype) documents persistent context and channel usage.
- [Playwright extensions](https://playwright.dev/docs/chrome-extensions) explicitly says sideloading flags no longer work in branded Chrome/Edge; Playwright Chromium with a persistent context is the supported option.
- [Microsoft Playwright LICENSE](https://github.com/microsoft/playwright/blob/main/LICENSE) is Apache-2.0. This does *not* waive separate redistribution conditions for all browser executables or other dependencies.
- [GenLogin overview](https://docs.genlogin.com/group-profiles/create-profile/overview) describes proprietary Titan fingerprint rendering. No public source code or licence authorizing redistribution of Titan was identified.
- [REA skill](https://github.com/morluto/rea/blob/main/.agents/skills/reverse-engineer-anything/SKILL.md) provides inspection workflows and evidence requirements; the runtime and an authorized GenLogin installer are not present.
- [Anthropic webapp-testing skill](https://github.com/anthropics/skills/blob/main/skills/webapp-testing/SKILL.md) recommends locally controlled Playwright browser tests, applied to a loopback test fixture here. No third-party skill code has been copied into the application.

## Allowed future engine roadmap

1. Record browser binary versions, native flags, lifecycle and matching Playwright API versions.
2. Test storage, compatibility, extensions, rendering and security headers against self-owned test pages.
3. Pin versions and audit licenses and dependencies in CI; do not silently download or run untrusted external binaries.
4. Build a privacy-respecting browser engine on legally usable open-source Chromium, if its maintenance budget is justified, with upstream security patching and reproducible builds.
5. Treat fingerprint behavior as an empirically measured browser characteristic, not a promise of impersonation or Sybil immunity.

## Explicit non-goals

Extracting Titan proprietary code without adequate rights, copying undisclosed fingerprint algorithms, or using profile impersonation specifically to evade identity/Sybil detection is not a valid parity gate. A functional comparator must use lawful observable behavior and legitimate product workflows.
