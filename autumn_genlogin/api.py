"""Opt-in, loopback-only bearer-auth API. Disabled unless explicitly enabled."""
from __future__ import annotations

import hmac
import json
import re
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class APIProblem(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Route:
    method: str
    pattern: re.Pattern
    handler: str
    service: str | None = None
    profile: bool = False
    command: str | None = None


def _route(method, path, handler, *, service=None, profile=False, command=None):
    return Route(method, re.compile(path), handler, service, profile, command)


# Patterns are compiled once, and never interpreted as code from HTTP input.
# Keep the established GET/POST trailing slash contract and optional services.
_PROFILE = r"/v1/profiles/(?P<id>[^/]*)"
_BATCH = r"/v1/batches/(?P<id>[^/]+)"
ROUTES = (
    _route("GET", r"/v1/health", "health"),
    _route("GET", r"/v1/profiles", "profiles"),
    _route("GET", r"/v1/schedules", "schedules", service="schedules"),
    _route("GET", r"/v1/schedules/history", "schedule_history", service="schedules"),
    _route("GET", r"/v1/batches", "batches", service="batches"),
    _route("GET", _BATCH + r"/*", "batch", service="batches"),
    _route("GET", _PROFILE + r"/recording", "recording", profile=True),
    _route("GET", _PROFILE + r"/runs/latest", "latest_run", profile=True),
    _route("POST", r"/v1/batches", "start_batch", service="batches"),
    _route("POST", _BATCH + r"/cancel", "cancel_batch", service="batches"),
    _route("POST", _PROFILE + r"/open", "profile_command", profile=True, command="start"),
    _route("POST", _PROFILE + r"/stop", "profile_command", profile=True, command="stop"),
    _route("POST", _PROFILE + r"/run", "run_steps", profile=True),
    _route("POST", _PROFILE + r"/run-graph", "run_graph", profile=True),
    _route("POST", _PROFILE + r"/record-start", "profile_command", profile=True, command="start_recording"),
    _route("POST", _PROFILE + r"/record-stop", "profile_command", profile=True, command="stop_recording"),
    _route("POST", _PROFILE + r"/cancel", "profile_command", profile=True, command="cancel"),
    # Historical behavior resolves the profile before rejecting an unknown
    # action. No dynamic command is selected by the untrusted path.
    _route("POST", _PROFILE + r"/[^/]+", "not_found", profile=True),
)


class LocalAPI:
    def __init__(self, store, manager, schedules=None, batches=None):
        self.store = store
        self.manager = manager
        self.schedules = schedules
        self.batches = batches
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
                return hmac.compare_digest(actual.encode("utf-8"),
                    ("Bearer " + controller.token).encode("utf-8"))

            def _body(self):
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 32768:
                    raise ValueError("Invalid request length or payload too large")
                return json.loads(self.rfile.read(length) or b"{}")

            def _resolve_profile(self, ident, method):
                try:
                    return controller.store.get(ident).id
                except KeyError:
                    raise APIProblem(404, "Profile not found" if method == "GET"
                                     else "Requested resource not found") from None
                except ValueError:
                    if method == "GET":
                        raise APIProblem(400, "Invalid profile ID") from None
                    raise

            def _match(self, method, path):
                # GET collection endpoints have exact paths; historical POST
                # endpoints and GET batch detail accept trailing slashes.
                if method == "POST":
                    path = "/" + path.strip("/")
                for route in ROUTES:
                    if route.method != method:
                        continue
                    if route.service and getattr(controller, route.service) is None:
                        continue
                    match = route.pattern.fullmatch(path)
                    if match:
                        return route, match.groupdict().get("id")
                raise APIProblem(404, "Not found")

            def do_GET(self):
                self._serve("GET")

            def do_POST(self):
                self._serve("POST")

            def _serve(self, method):
                if not self._authorized():
                    return self._json(401, {"error": "Unauthorized"})
                try:
                    parsed = urlparse(self.path)
                    # Preserve the previous body-validation order for POST.
                    data = self._body() if method == "POST" else None
                    route, ident = self._match(method, parsed.path)
                    if route.profile:
                        ident = self._resolve_profile(ident, method)
                    status, payload = getattr(self, "_handle_" + route.handler)(
                        ident, data, parse_qs(parsed.query), route.command)
                except APIProblem as exc:
                    status, payload = exc.status, {"error": exc.message}
                except (sqlite3.Error, OSError):
                    status, payload = 503, {"error": "Local storage unavailable; run Diagnostics"}
                except (ValueError, TypeError) as exc:
                    status, payload = 400, {"error": str(exc)[:200] if method == "POST"
                                            else "Invalid request parameters"}
                except KeyError:
                    status, payload = 404, {"error": "Requested resource not found"}
                except RuntimeError:
                    status, payload = 409, {"error": "Resource busy or action cannot be started"}
                self._json(status, payload)

            def _handle_health(self, *_):
                return 200, {"status": "ok", "running": controller.manager.count()}

            def _handle_profiles(self, *_):
                return 200, {"profiles": [
                    {"id": p.id, "name": p.name, "group": p.group_name,
                     "running": controller.manager.active(p.id)}
                    for p in controller.store.all()]}

            def _handle_schedules(self, *_):
                return 200, {"schedules": [
                    {"id": job.id, "profile_id": job.profile_id,
                     "next_run_utc": job.next_run_utc, "interval_seconds": job.interval_seconds,
                     "enabled": job.enabled, "last_status": job.last_status,
                     "last_error": job.last_error} for job in controller.schedules.list()]}

            def _handle_schedule_history(self, ident, data, params, command):
                limit = int(params.get("limit", ["50"])[0])
                schedule_id = params.get("schedule_id", [None])[0]
                return 200, {"runs": [
                    {"id": run.id, "job_id": run.job_id, "profile_id": run.profile_id,
                     "started_utc": run.started_utc, "finished_utc": run.finished_utc,
                     "status": run.status, "error_type": run.error_type}
                    for run in controller.schedules.history(schedule_id, limit)]}

            def _handle_batches(self, ident, data, params, command):
                limit = int(params.get("limit", ["20"])[0])
                return 200, {"batches": controller.batches.list(limit=limit)}

            def _handle_batch(self, ident, *_):
                try:
                    record = controller.batches.get(ident)
                except KeyError:
                    raise APIProblem(404, "Batch not found") from None
                return 200, {"batch": record}

            def _handle_recording(self, ident, *_):
                return 200, {"steps": controller.manager.recorded_steps(ident)}

            def _handle_latest_run(self, ident, *_):
                result = controller.manager.last_run(ident)
                if result is None:
                    raise APIProblem(404, "No recent workflow run")
                return 200, {"run": result}

            def _handle_start_batch(self, ident, data, *_):
                if not isinstance(data, dict):
                    raise ValueError("Expected JSON object")
                batch_id = controller.batches.start(data.get("profile_ids"),
                    data.get("workflow"), max_parallel=data.get("max_parallel", 3))
                return 202, {"accepted": True, "batch_id": batch_id}

            def _handle_cancel_batch(self, ident, *_):
                try:
                    controller.batches.cancel(ident)
                except KeyError:
                    raise APIProblem(404, "Batch is not active in this application") from None
                return 202, {"accepted": True}

            def _handle_profile_command(self, ident, data, params, command):
                # The command originates solely from the immutable route table.
                getattr(controller.manager, command)(ident)
                return 202, {"accepted": True}

            def _handle_run_steps(self, ident, data, *_):
                if not isinstance(data, dict) or "steps" not in data:
                    raise ValueError("Missing required field: steps")
                controller.manager.run_steps(ident, data["steps"])
                return 202, {"accepted": True}

            def _handle_run_graph(self, ident, data, *_):
                if not isinstance(data, dict) or "graph" not in data:
                    raise ValueError("Missing required field: graph")
                controller.manager.run_graph(ident, data["graph"])
                return 202, {"accepted": True}

            def _handle_not_found(self, *_):
                raise APIProblem(404, "Not found")

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="local-api", daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
            if self.thread and self.thread is not threading.current_thread():
                self.thread.join(timeout=5)
            self.thread = None
