"""Opt-in, loopback-only bearer-auth API. Disabled unless explicitly enabled."""
from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class LocalAPI:
    def __init__(self, store, manager):
        self.store = store
        self.manager = manager
        self.token = secrets.token_urlsafe(32)
        self.server = None
        self.thread = None

    def start(self, port: int = 8765) -> None:
        if self.server:
            raise ValueError("API already running")
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                return

            def _json(self, code, payload):
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _authorized(self):
                actual = self.headers.get("Authorization", "")
                if not hmac.compare_digest(actual, "Bearer " + controller.token):
                    self._json(401, {"error": "Unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._authorized():
                    return
                path = urlparse(self.path).path
                if path == "/v1/health":
                    self._json(200, {"status": "ok", "running": controller.manager.count()})
                elif path == "/v1/profiles":
                    self._json(200, {"profiles": [
                        {"id": p.id, "name": p.name, "group": p.group_name, "running": controller.manager.active(p.id)}
                        for p in controller.store.all()
                    ]})
                else:
                    self._json(404, {"error": "Not found"})

            def do_POST(self):
                if not self._authorized():
                    return
                try:
                    if int(self.headers.get("Content-Length", "0")) > 32768:
                        raise ValueError("Payload too large")
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length < 0:
                        raise ValueError("Invalid request length")
                    data = json.loads(self.rfile.read(content_length) or b"{}")
                    parts = urlparse(self.path).path.strip("/").split("/")
                    if len(parts) != 4 or parts[:2] != ["v1", "profiles"]:
                        self._json(404, {"error": "Not found"})
                        return
                    pid, action = parts[2:]
                    controller.store.get(pid)
                    if action == "open":
                        controller.manager.start(pid)
                    elif action == "stop":
                        controller.manager.stop(pid)
                    elif action == "run":
                        controller.manager.run_steps(pid, data["steps"])
                    elif action == "cancel":
                        controller.manager.cancel(pid)
                    else:
                        self._json(404, {"error": "Not found"})
                        return
                    self._json(202, {"accepted": True})
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    self._json(400, {"error": str(exc)[:200]})
                except KeyError:
                    self._json(404, {"error": "Profile not found or required field missing"})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="local-api", daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
