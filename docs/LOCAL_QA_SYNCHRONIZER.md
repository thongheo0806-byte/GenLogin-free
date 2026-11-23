# Experimental Local QA Synchronizer

**Status:** Development-only. This is not a full GenLogin Sync Actions
replacement and must not be used to automate personal accounts.
**EXE release remains HOLD.**

## Verified intended behavior

AutumnGenLogin has a single Playwright asyncio owner thread, with separate
persistent Chromium contexts. This experiment uses that architecture to
mirror **only a marked button click on a local QA page**, rather than opening
an unprotected cross-profile automation channel.

1. Start 2-6 independent Chromium profiles from the same user-controlled
   test origin, such as `http://127.0.0.1:9000`. They must all be in the same
   profile group. Select the intended master profile in Profiles.
2. On the Local QA sync tab, choose **Start local QA click sync** and confirm.
   Only 1-5 *already open* follower profiles in the selected group will be used.
3. A test page must explicitly mark safe button elements:
   `<button id="verify" data-autumn-qa-click="1">Check</button>`.
4. Clicking a marked button in the master triggers the single Playwright
   binding. The handler accepts only `{action:"click", id:"verify"}`
   with a bounded ASCII id and main-frame source. It verifies the master and
   each follower still show the **same literal 127.0.0.1 origin**.
5. Eligible follower buttons with matching IDs receive individual native
   Playwright clicks. No background retry or click on other selectors.
   Missing buttons and closed/occupied contexts count as failed mirrors.
6. **Stop QA sync** disarms the binding. No profiles are closed or shared.
   The experiment auto-disarms after at most 50 mirrored follower clicks.
   Nothing is saved or transmitted to the team hub.

## Strict exclusions

- External websites, LAN/remote hosts, HTTPS sites and browser logins.
- Typing/keyboard content, usernames/passwords, form submissions, cookies,
  local storage, credentials, navigation and screenshots.
- Synchronizing web requests, WebRTC, browser fingerprints, extension state,
  arbitrary DOM events, image recognition, OS-level mouse movements or frames.
- Claiming interoperability with GenLogin's proprietary synchronizer,
  Titan browser or evasion of website abuse/anti-fraud policies.

## Verification

`test_qa_sync.py` checks origin/ID/count restrictions.
`test_shared_browser_integration.py` opens **three real Chromium
persistent contexts** on a synthetic in-process local test server,
clicks a marked master button, verifies two followers receive the
result, stops the mirror and checks future master clicks do not propagate.

This still needs long-session tests, concurrency/failure injection,
GUI keyboard and accessibility acceptance before any wider operation.

## 2026-11-23 per-document live mirror safeguards

- The source/master tab and every follower must represent the **same local
  page route**, not merely the same `127.0.0.1:port` origin. Paths and query
  strings are compared in memory; fragment-only differences are ignored.
  Neither path nor query is saved or logged.
- For nested iframes, each follower's matching DOM iframe must resolve to an
  actual Frame with the same local route or identical special document
  `about:srcdoc` / `about:blank`. A follower iframe navigated to a foreign
  origin, another route or an ambiguous selector causes a **failed delivery**,
  never a guessed click.
- A synthetic real-Chromium test exercises two followers where one navigates
  to another localhost route with the same visible QA button ID. Only the
  still-matching follower may receive the next click.
- This is a safety boundary for **local QA pages only**. It is not full
  keyboard/text/navigation mirroring, site-account synchronization or
  GenLogin/Titan parity. Human-confirmed website-specific consent, trusted
  event provenance and stronger page identity checks remain separate work.
