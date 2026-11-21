"""Single synthetic AI browser-use demonstration, inside a pre-isolated container.

DO NOT start with the user's real Chrome, profiles, cookies or keys.
DO NOT import this from AutumnGenLogin. Browser-use 1.0 agents execute
model-written Python and are NOT safe merely because domains are allowlisted.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from pathlib import Path
import tempfile
import threading

from .policy import BROWSER_USE_VERSION, MODEL_BASE_URL, validate_environment

FIXTURE = b"""<!doctype html><meta charset="utf-8">
<title>Autumn isolated AI fixture</title><main>
<h1>Local-only artificial test page</h1>
<button id="verify">Verify local fixture</button>
<output id="result" aria-live="polite">NOT-CLICKED</output>
</main>
<script>
document.querySelector('#verify').addEventListener('click', () => {
    document.querySelector('#result').textContent = 'TEST-OK';
});
</script>
"""


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(FIXTURE)))
        self.end_headers()
        self.wfile.write(FIXTURE)

    def log_message(self, *_):
        pass


def run_demo(config, *, agent_type, browser_type, llm_type) -> bool:
    """Use dependency injection so unit tests cannot accidentally start an AI."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True,
                              name="autumn-ai-lab-only-fixture")
    worker.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        task = config.fixture_task(origin)
        with tempfile.TemporaryDirectory(prefix="autumn-ai-fixture-") as workspace:
            # Always instantiate a brand-new ephemeral browser, never an
            # AutumnGenLogin profile directory or user's Chrome profile.
            browser = browser_type(
                "chromium", executable_path="/usr/bin/chromium",
                headless=True, allowed_domains=["127.0.0.1"]
            )
            llm = llm_type(config.model, base_url=MODEL_BASE_URL,
                           api_key="ollama")
            agent = agent_type(task, llm=llm, browser=browser,
                               workspace=workspace,
                               web_search=False, judge=False, use_vision=False)
            result = agent.run_sync(max_steps=config.max_steps,
                                    timeout=config.timeout_seconds)
            outcome = result.final_result()
            return isinstance(outcome, str) and "TEST-OK" in outcome
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def main() -> int:
    # The environment marker is only a preflight check. Docker's actual
    # internal-only network and mount policy enforce sandbox boundaries.
    try:
        cfg = validate_environment(os.environ,
                                   inside_container=Path("/.dockerenv").exists())
        if version("browser-use") != BROWSER_USE_VERSION:
            raise RuntimeError("Unexpected browser-use version; rebuild the pinned lab image")
        from browser_use import Agent, Browser, ChatOpenAI
        success = run_demo(cfg, agent_type=Agent,
                           browser_type=Browser, llm_type=ChatOpenAI)
        print(json.dumps({"experiment":"isolated-browser-use",
                          "status":"passed" if success else "not-verified"}))
        return 0 if success else 2
    except Exception as exc:
        # Do not print model messages, URLs, prompts, screenshots or credentials.
        print(json.dumps({"experiment":"isolated-browser-use",
                          "status":"failed",
                          "error_type":type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
