"""Opt-in, loopback-only bearer-auth API. Disabled unless explicitly enabled."""
from __future__ import annotations

import hmac
import sqlite3
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
                # compare_digest(str, str) rejects non-ASCII; bytes avoid a dropped connection.
                if not hmac.compare_digest(actual.encode("utf-8"), ("Bearer " + controller.token).encode("utf-8")):
                    self._json(401, {"error": "Unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._authorized():
                    return
                try:
                    self._do_get_authorized()
                except (sqlite3.Error, OSError):
                    self._json(503, {"error": "Local storage unavailable; run Diagnostics"})

            def _do_get_authorized(self):
                path = urlparse(self.path).path
                if path == "/v1/health":
                    self._json(200, {"status": "ok", "running": controller.manager.count()})
                elif path == "/v1/profiles":
                    self._json(200, {"profiles": [
                        {"id": p.id, "name": p.name, "group": p.group_name, "running": controller.manager.active(p.id)}
                        for p in controller.store.all()
                    ]})
                elif len(path.strip("/").split("/")) == 5 and path.endswith("/runs/latest"):
                    parts = path.strip("/").split("/")
                    if parts[:2] != ["v1", "profiles"]:
                        self._json(404, {"error": "Not found"})
                        return
                    try:
                        pid = controller.store.get(parts[2]).id
                    except KeyError:
                        self._json(404, {"error": "Profile not found"})
                        return
                    except ValueError:
                        self._json(400, {"error": "Invalid profile ID"})
                        return
                    result = controller.manager.last_run(pid)
                    if result is None:
                        self._json(404, {"error": "No recent workflow run"})
                    else:
                        self._json(200, {"run": result})
                else:
                    self._json(404, {"error": "Not found"})

            def do_POST(self):
                if not self._authorized():
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    if content_length < 0 or content_length > 32768:
                        raise ValueError("Invalid request length or payload too large")
                    data = json.loads(self.rfile.read(content_length) or b"{}")
                    parts = urlparse(self.path).path.strip("/").split("/")
                    if len(parts) != 4 or parts[:2] != ["v1", "profiles"]:
                        self._json(404, {"error": "Not found"})
                        return
                    pid, action = parts[2:]
                    pid = controller.store.get(pid).id
                    if action == "open":
                        controller.manager.start(pid)
                    elif action == "stop":
                        controller.manager.stop(pid)
                    elif action == "run":
                        if not isinstance(data, dict) or "steps" not in data:
                            raise ValueError("Missing required field: steps")
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
                    self._json(404, {"error": "Profile not found"})
                except (sqlite3.Error, OSError):
                    self._json(503, {"error": "Local storage unavailable; run Diagnostics"})

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="local-api", daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
