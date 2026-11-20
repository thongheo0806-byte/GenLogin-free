"""Safe stdlib Python client for AutumnGenLogin's opt-in local /v1 API.

This is an independently designed local API, not GenLogin protocol emulation.
All requests require a per-session bearer token. Redirects and proxies are
disabled to prevent forwarding that token outside the selected loopback host.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

from .graph import validate_graph
from .models import validated_steps

MAX_RESPONSE = 1024 * 1024


class LocalAPIError(RuntimeError):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message[:200]
        super().__init__(f"Local API status {status}: {self.message}")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise LocalAPIError(502, "Local API redirects are forbidden")


class AutumnAPIClient:
    """Opt-in local-only controller for one running desktop application."""

    def __init__(self, token: str, *, url: str = "http://127.0.0.1:8765",
                 timeout: float = 10):
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.port is None):
            raise ValueError("Local API URL must be http://127.0.0.1:PORT (or IPv6 loopback)")
        if type(timeout) not in {float, int} or not 0.5 <= timeout <= 60:
            raise ValueError("Timeout must be 0.5-60 seconds")
        if (not isinstance(token, str) or not 16 <= len(token) <= 256
            or not re.fullmatch(r"[\x21-\x7e]+", token)):
            raise ValueError("Invalid API bearer token")
        self.url = url.rstrip("/")
        self._token = token
        self.timeout = float(timeout)
        # Never honor HTTP_PROXY/HTTPS_PROXY or follow server-provided 30x
        # Location headers: both can leak local bearer tokens.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _RejectRedirects())

    def __repr__(self):
        return f"AutumnAPIClient(url={self.url!r}, token=<hidden>)"

    def _get(self, path: str, query: dict | None = None):
        return self._request("GET",path,query=query)

    def _post(self, path: str, payload: dict):
        return self._request("POST",path,payload=payload)

    def _request(self, method: str, path: str, *, payload: dict | None = None,
                 query: dict | None = None):
        if not path.startswith("/") or "://" in path or "#" in path:
            raise ValueError("Invalid API request path")
        suffix = ("?" + urllib.parse.urlencode(query)) if query else ""
        raw = json.dumps(payload,separators=(",",":")).encode("utf-8") if payload is not None else None
        if raw is not None and len(raw) > 32768:
            raise ValueError("API payload exceeds 32 KiB")
        request = urllib.request.Request(self.url+path+suffix,
              method=method,data=raw,
              headers={"Authorization":"Bearer "+self._token,
                       "Content-Type":"application/json","Accept":"application/json"})
        try:
            with self._opener.open(request,timeout=self.timeout) as resp:
                if resp.status not in (200,201,202):
                    raise LocalAPIError(resp.status,"Unexpected response status")
                data = resp.read(MAX_RESPONSE+1)
                if len(data)>MAX_RESPONSE:
                    raise LocalAPIError(502,"Response exceeds safety limit")
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            try:
                response = json.loads(exc.read(4096))
                message = response.get("error","Request rejected") if isinstance(response,dict) else "Request rejected"
            except (UnicodeError, ValueError):
                message = "Request rejected"
            raise LocalAPIError(exc.code,str(message)) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            # Never serialize raw URL objects, credentials or exception bodies.
            raise LocalAPIError(503,"Local API is unavailable") from None
        except (UnicodeError, ValueError) as exc:
            raise LocalAPIError(502,"Local API returned invalid JSON") from exc

    @staticmethod
    def _id(value: str) -> str:
        return str(UUID(value))

    def health(self) -> dict:
        return self._get("/v1/health")

    def profiles(self) -> list[dict]:
        return self._get("/v1/profiles")["profiles"]

    def open_profile(self, profile_id: str) -> dict:
        return self._post(f"/v1/profiles/{self._id(profile_id)}/open",{})

    def stop_profile(self, profile_id: str) -> dict:
        return self._post(f"/v1/profiles/{self._id(profile_id)}/stop",{})

    def cancel_run(self, profile_id: str) -> dict:
        return self._post(f"/v1/profiles/{self._id(profile_id)}/cancel",{})

    def run_steps(self, profile_id: str, steps: list[dict]) -> dict:
        return self._post(f"/v1/profiles/{self._id(profile_id)}/run",
                          {"steps":validated_steps(steps)})

    def run_graph(self, profile_id: str, graph: dict) -> dict:
        return self._post(f"/v1/profiles/{self._id(profile_id)}/run-graph",
                          {"graph":validate_graph(graph)})

    def latest_run(self, profile_id: str) -> dict:
        return self._get(f"/v1/profiles/{self._id(profile_id)}/runs/latest")["run"]

    def recorded_steps(self, profile_id: str) -> list[dict]:
        return self._get(f"/v1/profiles/{self._id(profile_id)}/recording")["steps"]

    def start_recording(self, profile_id: str) -> dict:
        return self._post(f"/v1/profiles/{self._id(profile_id)}/record-start",{})

    def stop_recording(self, profile_id: str) -> dict:
        return self._post(f"/v1/profiles/{self._id(profile_id)}/record-stop",{})

    def schedules(self) -> list[dict]:
        return self._get("/v1/schedules")["schedules"]

    def schedule_history(self, *, job_id: str | None = None, limit: int = 50) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Schedule history limit must be 1-200")
        params = {"limit":limit}
        if job_id is not None:
            params["schedule_id"] = self._id(job_id)
        return self._get("/v1/schedules/history",params)["runs"]

    def start_batch(self, profile_ids: list[str], workflow: dict | list,
                    *, max_parallel: int = 3) -> str:
        if type(max_parallel) is not int or not 1 <= max_parallel <= 6:
            raise ValueError("Batch parallelism must be 1-6")
        if not isinstance(profile_ids,list) or not 1 <= len(profile_ids) <= 200:
            raise ValueError("Batch requires 1-200 profile UUIDs")
        ids=[self._id(pid) for pid in profile_ids]
        if len(ids)!=len(set(ids)):
            raise ValueError("Duplicate profile UUIDs")
        flow = validated_steps(workflow) if isinstance(workflow,list) else validate_graph(workflow)
        return self._post("/v1/batches",{
            "profile_ids":ids,"workflow":flow,"max_parallel":max_parallel})["batch_id"]

    def batches(self, *, limit: int = 20) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 30:
            raise ValueError("Batch limit must be 1-30")
        return self._get("/v1/batches",{"limit":limit})["batches"]

    def batch(self, batch_id: str) -> dict:
        return self._get(f"/v1/batches/{self._id(batch_id)}")["batch"]

    def cancel_batch(self, batch_id: str) -> dict:
        return self._post(f"/v1/batches/{self._id(batch_id)}/cancel",{})
