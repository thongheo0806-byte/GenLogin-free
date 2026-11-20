"""Bounded local batch automation for a selected set of browser profiles.

Runs prevalidated data-only workflows through SharedBrowserManager. This is
not a synchronizer or a stealth/anti-fraud engine: profiles execute separately.
Results contain only UUIDs, terminal statuses and safe exception type names;
input text, extracted page content and credentials are never recorded here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
import threading
import time
from uuid import UUID, uuid4

from .graph import validate_graph
from .models import validated_steps


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _error_type(error: object) -> str:
    name = str(error).partition(":")[0]
    return name[:80] if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,79}", name) else "AutomationError"


class BatchRunner:
    """Daemon worker pool: bounded per batch, never silently repeats a profile."""

    MAX_PROFILES = 200
    MAX_SAVED_BATCHES = 30
    TERMINAL = frozenset({"succeeded", "failed", "cancelled", "uncertain"})

    def __init__(self, store, manager, *, max_runtime_seconds: int = 3600):
        if type(max_runtime_seconds) is not int or not 30 <= max_runtime_seconds <= 7200:
            raise ValueError("Batch runtime limit must be 30-7200 seconds")
        self.store = store
        self.manager = manager
        self.max_runtime_seconds = max_runtime_seconds
        self._lock = threading.RLock()
        self._batches: dict[str, dict] = {}
        self._cancelled: dict[str, threading.Event] = {}

    def start(self, profile_ids: list[str], workflow: dict | list, *, max_parallel: int = 3) -> str:
        if not isinstance(profile_ids, list) or not 1 <= len(profile_ids) <= self.MAX_PROFILES:
            raise ValueError("Batch requires 1-200 profile IDs")
        if any(not isinstance(pid, str) for pid in profile_ids):
            raise ValueError("Profile IDs must be UUID strings")
        ids = [str(UUID(pid)) for pid in profile_ids]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate profile IDs in batch")
        if type(max_parallel) is not int or not 1 <= max_parallel <= min(6, self.manager.MAX_BROWSERS):
            raise ValueError("Batch parallelism must be 1-6")
        # Validate everything before scheduling any browser work.
        validated = validated_steps(workflow) if isinstance(workflow, list) else validate_graph(workflow)
        for pid in ids:
            self.store.get(pid)
        ident = str(uuid4())
        with self._lock:
            if len(self._batches) >= self.MAX_SAVED_BATCHES:
                older = [key for key, value in self._batches.items()
                         if value["status"] in {"succeeded", "partial", "cancelled"}]
                if not older:
                    raise RuntimeError("Too many active batches; wait or cancel some")
                del self._batches[older[0]]
                self._cancelled.pop(older[0], None)
            self._batches[ident] = {
                "id": ident, "created_utc": _utc(), "finished_utc": None,
                "status": "running", "max_parallel": max_parallel,
                "cancel_requested": False,
                "items": [
                    {"profile_id": pid, "status": "queued", "run_id": None, "error_type": ""}
                    for pid in ids
                ],
            }
            self._cancelled[ident] = threading.Event()
        # Browser work always happens off the UI/API threads.
        for index in range(min(max_parallel, len(ids))):
            threading.Thread(
                target=self._worker, args=(ident, deepcopy(validated)),
                name=f"autumn-batch-{ident[:8]}-{index}", daemon=True,
            ).start()
        return ident

    def get(self, batch_id: str) -> dict:
        key = str(UUID(batch_id))
        with self._lock:
            if key not in self._batches:
                raise KeyError("Batch not found")
            return deepcopy(self._batches[key])

    def list(self, limit: int = 20) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= self.MAX_SAVED_BATCHES:
            raise ValueError("Batch limit must be 1-30")
        with self._lock:
            keys = list(self._batches)[-limit:][::-1]
            return [deepcopy(self._batches[key]) for key in keys]

    def _finish(self, batch_id: str, profile_id: str, status: str, error: object = ""):
        if status not in self.TERMINAL:
            status, error = "uncertain", "AutomationError"
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return
            for item in batch["items"]:
                if item["profile_id"] == profile_id:
                    if item["status"] not in self.TERMINAL:
                        item["status"] = status
                        item["error_type"] = _error_type(error) if error else ""
                    break
            self._update_batch_status(batch)

    @staticmethod
    def _update_batch_status(batch):
        statuses = [item["status"] for item in batch["items"]]
        if not all(status in BatchRunner.TERMINAL for status in statuses):
            return
        if all(status == "succeeded" for status in statuses):
            batch["status"] = "succeeded"
        elif batch["cancel_requested"] and all(status in {"succeeded", "cancelled"} for status in statuses):
            batch["status"] = "cancelled"
        else:
            batch["status"] = "partial"
        batch["finished_utc"] = _utc()

    def _next(self, batch_id: str):
        with self._lock:
            batch = self._batches[batch_id]
            for item in batch["items"]:
                if item["status"] == "queued":
                    if batch["cancel_requested"]:
                        item["status"] = "cancelled"
                        self._update_batch_status(batch)
                        continue
                    item["status"] = "submitting"
                    return item["profile_id"]
            self._update_batch_status(batch)
            return None

    def _cancel_own_run(self, profile_id: str, run_id: str | None) -> None:
        if not run_id:
            return
        try:
            latest = self.manager.last_run(profile_id)
            if latest and latest.get("id") == run_id:
                self.manager.cancel(profile_id)
        except (RuntimeError, ValueError, KeyError):
            pass

    def _worker(self, batch_id: str, workflow: dict | list):
        while True:
            pid = self._next(batch_id)
            if pid is None:
                return
            complete = threading.Event()
            result: dict[str, object] = {}
            already_open = self.manager.active(pid)

            def on_finish(status: str, error: str | None):
                result["status"] = status
                result["error"] = error
                complete.set()

            try:
                run_id = self.manager.start_workflow(pid, deepcopy(workflow), on_finish=on_finish)
            except Exception as exc:
                self._finish(batch_id, pid, "failed", type(exc).__name__)
                continue

            with self._lock:
                batch = self._batches[batch_id]
                for item in batch["items"]:
                    if item["profile_id"] == pid:
                        item["run_id"] = run_id
                        if item["status"] == "submitting":
                            item["status"] = "running"
                        break
                cancel = self._cancelled[batch_id]

            started = time.monotonic()
            cancellation_sent = False
            while not complete.wait(0.2):
                if cancel.is_set() and not cancellation_sent:
                    self._cancel_own_run(pid, run_id)
                    cancellation_sent = True
                if time.monotonic()-started >= self.max_runtime_seconds:
                    self._cancel_own_run(pid, run_id)
                    self._finish(batch_id, pid, "uncertain", "TimeoutError")
                    break
            if complete.is_set():
                terminal = str(result.get("status", "uncertain"))
                self._finish(batch_id, pid, terminal, result.get("error"))
            if not already_open:
                # Do not oversubscribe a concurrency slot while auto-close is
                # still releasing the previous profile's persistent context.
                deadline = time.monotonic()+15
                while self.manager.active(pid) and time.monotonic() < deadline:
                    time.sleep(0.1)

    def cancel(self, batch_id: str) -> None:
        key = str(UUID(batch_id))
        with self._lock:
            batch = self._batches.get(key)
            if batch is None:
                raise KeyError("Batch not found")
            batch["cancel_requested"] = True
            self._cancelled[key].set()
            active = [(item["profile_id"], item["run_id"]) for item in batch["items"]
                      if item["status"] == "running" and item["run_id"]]
            for item in batch["items"]:
                if item["status"] == "queued":
                    item["status"] = "cancelled"
            self._update_batch_status(batch)
        for pid, run_id in active:
            self._cancel_own_run(pid,run_id)

    def cancel_all(self) -> None:
        with self._lock:
            keys = list(self._batches)
        for key in keys:
            self.cancel(key)
