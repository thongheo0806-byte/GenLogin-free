"""Durable local automation schedule with atomic claims and UTC intervals.

Never executes shell, Python, or JavaScript. Jobs refer to strictly validated
workflow steps or graph data and are dispatched to an injected browser manager.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID, uuid4

from .graph import validate_graph
from .models import validated_steps
from .storage import Store


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime) -> str:
    if t.tzinfo is None: raise ValueError("Schedule requires offset-aware datetime")
    return t.astimezone(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Job:
    id: str
    profile_id: str
    workflow: dict | list
    next_run_utc: str
    interval_seconds: int | None
    enabled: bool
    last_status: str
    last_error: str


class ScheduleStore:
    def __init__(self, store: Store):
        self.store = store
        with store._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY, profile_id TEXT NOT NULL,
                workflow_json TEXT NOT NULL, next_run_utc TEXT NOT NULL,
                interval_seconds INTEGER, enabled INTEGER NOT NULL DEFAULT 1,
                last_status TEXT NOT NULL DEFAULT 'pending',
                last_error TEXT NOT NULL DEFAULT ''
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS schedules_due_idx ON schedules(enabled,next_run_utc)")

    @staticmethod
    def _check_workflow(workflow):
        if isinstance(workflow, list): return validated_steps(workflow)
        return validate_graph(workflow)

    def add(self, profile_id: str, workflow: dict | list, next_run: datetime,
            interval_seconds: int | None = None) -> str:
        pid = str(UUID(profile_id))
        self.store.get(pid)
        flow = self._check_workflow(workflow)
        if interval_seconds is not None and (type(interval_seconds) is not int or not 60 <= interval_seconds <= 31_536_000):
            raise ValueError("Repeat interval must be 60 seconds to 1 year")
        job_id = str(uuid4())
        with self.store._connect() as c:
            c.execute("INSERT INTO schedules (id,profile_id,workflow_json,next_run_utc,interval_seconds) VALUES(?,?,?,?,?)",
                      (job_id, pid, json.dumps(flow), iso(next_run), interval_seconds))
        return job_id

    def list(self) -> list[Job]:
        with self.store._connect() as c:
            rows = c.execute("SELECT * FROM schedules ORDER BY next_run_utc").fetchall()
        return [Job(id=r["id"], profile_id=r["profile_id"],workflow=json.loads(r["workflow_json"]),
                    next_run_utc=r["next_run_utc"],interval_seconds=r["interval_seconds"],enabled=bool(r["enabled"]),
                    last_status=r["last_status"],last_error=r["last_error"]) for r in rows]

    def remove(self, job_id: str) -> None:
        with self.store._connect() as c:
            c.execute("DELETE FROM schedules WHERE id=?", (str(UUID(job_id)),))

    def claim_due(self, now: datetime | None = None, limit: int = 5) -> list[Job]:
        """Claim exactly once on this local database, even from multiple schedulers."""
        now = now or utcnow()
        now_s = iso(now)
        limit = max(1, min(20, limit))
        claimed=[]
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            rows = c.execute("SELECT * FROM schedules WHERE enabled=1 AND next_run_utc<=? ORDER BY next_run_utc LIMIT ?",
                             (now_s, limit)).fetchall()
            for r in rows:
                interval = r["interval_seconds"]
                if interval:
                    previous = datetime.fromisoformat(r["next_run_utc"])
                    # Skip missed intervals instead of backfilling thousands of jobs.
                    skips = max(1, int((now-previous).total_seconds()//interval)+1)
                    next_time = iso(previous + timedelta(seconds=skips*interval))
                    c.execute("UPDATE schedules SET next_run_utc=?,last_status='dispatched',last_error='' WHERE id=?",
                              (next_time,r["id"]))
                else:
                    c.execute("UPDATE schedules SET enabled=0,last_status='dispatched',last_error='' WHERE id=?",(r["id"],))
                claimed.append(Job(id=r["id"],profile_id=r["profile_id"],workflow=json.loads(r["workflow_json"]),
                                   next_run_utc=r["next_run_utc"],interval_seconds=interval,
                                   enabled=bool(interval),last_status="dispatched",last_error=""))
        return claimed

    def record_error(self, job_id: str, error: str) -> None:
        with self.store._connect() as c:
            c.execute("UPDATE schedules SET last_status='error',last_error=? WHERE id=?", (error[:400],job_id))


class Scheduler:
    def __init__(self, store: ScheduleStore, dispatch: Callable[[str, dict | list], None], *, interval=1.0):
        self.store = store
        self.dispatch = dispatch
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._work,daemon=True,name="autumn-scheduler")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def _work(self):
        try:
            while not self._stop.is_set():
                try:
                    for job in self.store.claim_due():
                        try: self.dispatch(job.profile_id, job.workflow)
                        except (RuntimeError, OSError, ValueError, KeyError) as exc:
                            self.store.record_error(job.id, f"{type(exc).__name__}: {exc}")
                except sqlite3.Error:
                    # A locked or temporarily unavailable database must not kill
                    # the scheduler thread; the GUI diagnostics remains available.
                    pass
                self._stop.wait(self.interval)
        finally:
            self.store.store.close_thread_connection()
