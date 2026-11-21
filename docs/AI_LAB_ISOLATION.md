# Experimental browser-use AI agent: isolated synthetic fixture only

**Not a production AutumnGenLogin feature. Not a verified AI run.**
Updated **2026-11-21**. Source-only experiment. EXE build remains HOLD.

Reference upstream:
- [browser-use/browser-use](https://github.com/browser-use/browser-use)
  (MIT): latest stable tag verified at research time `1.0.7`, with
  `Agent(task, llm, browser=Browser('chromium'))`. We pin **exactly**
  `browser-use==1.0.7` in this isolated Docker image.
- The upstream README explicitly warns: the model can write arbitrary Python,
  read local files and leak values via screenshots; `allowed_domains` is a
  guard, **not a security sandbox**. Chromium CDP opens an unauthenticated
  loopback debugging port. Never attach this agent to a real user profile,
  desktop Chrome instance or stored credentials.

## Scope implemented

The self-contained `experiments/browser_use_lab/` folder is **not imported**
by the desktop application and is **not enabled by any UI or API endpoint**.

1. A separate Docker Compose stack uses an `internal: true` network with
   no published host ports. An Ollama service is reachable only by the
   isolated agent service. Runtime egress is denied by the network topology,
   rather than merely trusting an AI instruction.
2. The agent container has no bind mounts, non-root UID, dropped Linux
   capabilities, no-new-privileges, a read-only filesystem and bounded
   process/memory/shm resources. `/tmp` is ephemeral. It is **not** given
   `AUTUMN_GENLOGIN_HOME`, tokens, cloud keys or browser session files.
3. The Ollama service sees **only** an explicitly chosen offline model
   directory. Never point that mount to an application or personal folder.
   Its image must be explicitly chosen; no implicit version `latest`.
4. The agent creates a synthetic local page on `127.0.0.1` displaying a
   `Verify local fixture` button. Its task is fixed in audited Python.
   No arbitrary user prompt, external website, email, login or purchase.
5. The exact browser-use version is checked at runtime. Browser('chromium')
   uses a fresh ephemeral browser with no persistent user profile, and the
   LLM uses `ChatOpenAI(..., base_url=http://ollama:11434/v1)`.
   `web_search=False`, `judge=False`, `use_vision=False`, telemetry disabled.
   The agent is limited to six steps and a 90-second timeout.
6. The command prints only a synthetic pass/fail marker or sanitized
   exception type. Browser/agent state is destroyed when the container exits.

The `tests/test_ai_lab_policy.py` CI test uses a **fake agent** with a
real local HTTP fixture to check preflight logic, environment isolation,
model endpoint and bounded arguments. It **does not** install a real Ollama
model or attest actual browser-use inference quality.

## Running an operator-supervised proof of concept

**Optional and experimental**, after reviewing the exact upstream release,
the Dockerfile, image digests and the policy. Requires Docker Desktop / Linux
Docker plus an Ollama image and model pre-provisioned from approved sources.
When an offline model is not available, **do not run this experiment**.

Set the following *only* in your operator shell. No API keys:

```powershell
$env:AUTUMN_LAB_OLLAMA_IMAGE = 'ollama/ollama:REVIEWED_EXACT_TAG'
$env:AUTUMN_LAB_OLLAMA_MODELS = 'D:\\SAFE-LOCAL-MODEL-ONLY'
$env:AUTUMN_LAB_MODEL = 'your-already-installed-model:tag'
docker compose -f experiments/browser_use_lab/compose.yaml config
docker compose -f experiments/browser_use_lab/compose.yaml run --build --rm agent
```

The image tag and existing model name above are deliberately **not** fake
working defaults. The operator must choose and verify them before executing.
Do not enable automatic model pulls inside the runtime-isolated stack.
Ensure the prepared Ollama model store works read-only and has the requested
model; otherwise the experiment should fail safely.

### Limitations and future acceptance

- Container and Docker Desktop/WSL2 security, image integrity, GPU access,
  model file permissions, Chromium profile lifecycle and network egress
  require independent runtime verification, ideally on a fresh machine.
  The marker `AUTUMN_AI_LAB_ISOLATED=1` **does not** create a sandbox.
- The code may need compatibility fixes after the independent
  `browser-use==1.0.7` image and Ollama endpoint are actually executed.
  Source tests alone are not AI automation acceptance.
- No screenshot/secret leakage test is possible without a real model run,
  so the AI lab has no path into the production app until those checks pass.
- Even with `allowed_domains`, the agent may issue Python network requests;
  container network isolation is a required independent control.
- Do not use this for CAPTCHA bypass, anti-fraud evasion, Sybil activity,
  mass-login workflows, commercial websites or personal accounts.
- No consented GenLogin/Titan parity evidence is implied or acquired.
