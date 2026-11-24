"""Isolated Ollama -> bounded JSON decision -> trusted Chromium click proof.

Unlike the separate browser-use research agent, this experiment NEVER runs
model-written code, selectors, URLs or commands. Only a fixed synthetic task
and a model-selected option from an explicit finite allowlist are accepted.
No application data, real browser profiles, or user credentials are used.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from .policy import validate_environment

MODEL_URL = "http://ollama:11434/api/generate"
MAX_REPLY = 64 * 1024
LABELS = ("Inspect local fixture", "Verify local fixture", "Cancel local fixture")
TARGET_LABEL = LABELS[1]


def parse_choice(raw: str, allowed: tuple[str, ...]) -> str:
    """Reject extra fields, invalid choices, and ambiguous JSON."""
    def unique_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("Duplicate planner field")
            out[key] = value
        return out
    if not isinstance(raw, str) or len(raw) > 256:
        raise ValueError("Invalid planner response size")
    doc = json.loads(raw, object_pairs_hook=unique_pairs)
    if (not isinstance(doc, dict) or set(doc) != {"choice"}
            or not isinstance(doc["choice"], str) or doc["choice"] not in allowed):
        raise ValueError("Planner response outside allowlist")
    return doc["choice"]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Model endpoint redirect refused")


def model_choice(model: str, options: list[dict]) -> str:
    """Use a fixed isolated Ollama endpoint; never accept an endpoint from a model."""
    allowed = tuple(item["id"] for item in options)
    payload = {
        "model": model, "stream": False,
        "prompt": (
            "Choose the option whose label is exactly 'Verify local fixture'. "
            "Return only JSON with one key choice, containing the option ID. "
            "Options: " + json.dumps(options, ensure_ascii=True)
        ),
        "format": {
            "type": "object", "properties": {"choice": {"type": "string",
                                                            "enum": list(allowed)}},
            "required": ["choice"], "additionalProperties": False,
        },
        "options": {"temperature": 0, "num_predict": 64, "num_ctx": 1024},
    }
    request = Request(MODEL_URL, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"}, method="POST")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=120) as response:
        raw = response.read(MAX_REPLY + 1)
    if len(raw) > MAX_REPLY:
        raise ValueError("Ollama response too large")
    result = json.loads(raw)
    if (not isinstance(result, dict) or result.get("done") is not True
            or result.get("model") != model
            or type(result.get("eval_count")) is not int
            or result["eval_count"] <= 0):
        raise ValueError("No completed model inference evidence")
    return parse_choice(result.get("response"), allowed)


def run_trial(model: str, *, choose=model_choice) -> bool:
    """One model decision on a fresh randomized, entirely synthetic page."""
    from playwright.sync_api import sync_playwright
    labels = list(LABELS)
    secrets.SystemRandom().shuffle(labels)
    options = [{"id": f"option-{index + 1}", "label": label}
               for index, label in enumerate(labels)]
    correct = next(item["id"] for item in options if item["label"] == TARGET_LABEL)
    nonce = secrets.token_hex(16)
    verified = threading.Event()
    buttons = "".join(
        f'<button data-choice="{item["id"]}">{item["label"]}</button>'
        for item in options)
    page_html = (
        '<!doctype html><meta charset="utf-8"><title>Local fixture</title>'
        '<main>' + buttons + '<output id="result">NOT-CLICKED</output></main>'
        '<script>document.querySelectorAll("button").forEach(button=>'
        'button.addEventListener("click", event=>{'
        'if(!event.isTrusted)return;'
        'const id=button.dataset.choice;'
        'document.querySelector("#result").textContent=id;'
        'fetch("/verified",{method:"POST",headers:{"Content-Type":"text/plain"},'
        'body:' + json.dumps(nonce + ":") + '+id}).catch(()=>{});'
        '}));</script>'
    ).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(2)

        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page_html)))
            self.end_headers()
            self.wfile.write(page_html)

        def do_POST(self):
            expected = (nonce + ":" + correct).encode()
            if (self.path != "/verified"
                    or self.headers.get("Content-Type") != "text/plain"
                    or self.headers.get("Content-Length") != str(len(expected))
                    or self.rfile.read(len(expected)) != expected):
                self.send_error(400)
                return
            verified.set()
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path="/usr/bin/chromium", headless=True,
                args=["--renderer-process-limit=2"])
            try:
                context = browser.new_context()
                context.route("**/*", lambda route:
                    route.continue_() if route.request.url in
                    (origin + "/", origin + "/verified") else route.abort())
                page = context.new_page()
                page.goto(origin + "/", wait_until="domcontentloaded", timeout=15000)
                observed = page.locator("button[data-choice]").evaluate_all(
                    "(buttons) => buttons.map(b=>({id:b.dataset.choice,label:b.textContent}))")
                if observed != options:
                    return False
                choice = choose(model, observed)
                if not isinstance(choice, str) or choice not in {x["id"] for x in options}:
                    return False
                # Only the trusted executor creates a selector and clicks.
                locator = page.locator(f'button[data-choice="{choice}"]')
                if locator.count() != 1:
                    return False
                with page.expect_response(
                        lambda reply: reply.url == origin + "/verified",
                        timeout=8000) as response:
                    locator.click(timeout=5000)
                return (response.value.status == 204 and verified.is_set()
                        and choice == correct
                        and page.locator("#result").inner_text(timeout=5000) == correct)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def main() -> int:
    try:
        config = validate_environment(os.environ,
                                      inside_container=Path("/.dockerenv").exists())
        results = [run_trial(config.model) for _ in range(3)]
        # No model outputs, user data, page text or arbitrary code in logs.
        print(json.dumps({"experiment": "bounded-ollama-planner",
                          "verified_trials": sum(results), "total_trials": len(results),
                          "status": "passed" if all(results) else "not-verified"}))
        return 0 if all(results) else 2
    except Exception as exc:
        print(json.dumps({"experiment": "bounded-ollama-planner",
                          "status": "failed", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
