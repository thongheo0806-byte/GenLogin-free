"""Durable local automation schedule with atomic claims and UTC intervals.

Never executes shell, Python, or JavaScript. Jobs refer to strictly validated
workflow steps or graph data and are dispatched to an injected browser manager.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
import re
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
    dispatch_id: str | None = None


@dataclass(frozen=True)
class RunRecord:
    id: str
    job_id: str
    profile_id: str
    started_utc: str
    finished_utc: str | None
    status: str
    error_type: str


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
            c.execute("""CREATE TABLE IF NOT EXISTS schedule_runs (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                started_utc TEXT NOT NULL,
                finished_utc TEXT,
                status TEXT NOT NULL,
                error_type TEXT NOT NULL DEFAULT ''
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS schedule_runs_job_idx ON schedule_runs(job_id)")
            c.execute("CREATE INDEX IF NOT EXISTS schedule_runs_profile_idx ON schedule_runs(profile_id)")

    @staticmethod
    def _check_workflow(workflow):
        if isinstance(workflow, list): return validated_steps(workflow)
        return validate_graph(workflow)

    @staticmethod
    def _stored_workflow(raw: str) -> dict | list:
        """Decode persisted jobs without exposing potentially sensitive source."""
        try:
            workflow = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError("InvalidStoredWorkflow") from exc
        if not isinstance(workflow, (dict, list)):
            raise ValueError("InvalidStoredWorkflow")
        return workflow

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
        """A damaged persisted workflow must not take down GUI or the API."""
        jobs = []
        with self.store._connect() as c:
            rows = c.execute("SELECT * FROM schedules ORDER BY next_run_utc").fetchall()
            for r in rows:
                try:
                    workflow = self._stored_workflow(r["workflow_json"])
                    enabled, status, error = bool(r["enabled"]), r["last_status"], r["last_error"]
                except ValueError:
                    workflow, enabled, status, error = [], False, "error", "InvalidStoredWorkflow"
                    # Compare raw data to avoid quarantining a concurrently edited job.
                    c.execute(
                        "UPDATE schedules SET enabled=0,last_status='error',last_error=? "
                        "WHERE id=? AND workflow_json=?",
                        (error, r["id"], r["workflow_json"]),
                    )
                jobs.append(Job(id=r["id"], profile_id=r["profile_id"], workflow=workflow,
                                next_run_utc=r["next_run_utc"], interval_seconds=r["interval_seconds"],
                                enabled=enabled, last_status=status, last_error=error))
        return jobs

    def remove(self, job_id: str) -> None:
        jid = str(UUID(job_id))
        with self.store._connect() as c:
            c.execute("DELETE FROM schedule_runs WHERE job_id=?", (jid,))
            c.execute("DELETE FROM schedules WHERE id=?", (jid,))

    def history(self, job_id: str | None = None, limit: int = 50) -> list[RunRecord]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("History limit must be 1-200")
        with self.store._connect() as c:
            if job_id is not None:
                rows = c.execute("SELECT * FROM schedule_runs WHERE job_id=? ORDER BY rowid DESC LIMIT ?",
                                 (str(UUID(job_id)), limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM schedule_runs ORDER BY rowid DESC LIMIT ?",(limit,)).fetchall()
        return [RunRecord(**dict(row)) for row in rows]

    def claim_due(self, now: datetime | None = None, limit: int = 5) -> list[Job]:
        """Claim exactly once on this local database, even from multiple schedulers."""
        now = now or utcnow()
        now_s = iso(now)
        limit = max(1, min(20, limit))
        claimed=[]
        with self.store._connect() as c:
            # The scheduler polls once per second. Avoid an EXCLUSIVE writer
            # reservation during idle periods so GUI/API writes are not
            # needlessly queued behind a job-free polling transaction.
            if c.execute(
                "SELECT 1 FROM schedules WHERE enabled=1 AND next_run_utc<=? LIMIT 1",
                (now_s,),
            ).fetchone() is None:
                return claimed
            # A concurrent scheduler may have claimed the row since the
            # optimistic read. Recheck inside the write transaction to
            # preserve exactly-once claims across processes and threads.
            c.execute("BEGIN IMMEDIATE")
            rows = c.execute("SELECT * FROM schedules WHERE enabled=1 AND next_run_utc<=? ORDER BY next_run_utc LIMIT ?",
                             (now_s, limit)).fetchall()
            for r in rows:
                # Validate every stored row before making a dispatch record.
                # One corrupt row must never block healthy due jobs behind it.
                try:
                    workflow = self._stored_workflow(r["workflow_json"])
                    interval = r["interval_seconds"]
                    next_time = None
                    if interval:
                        if type(interval) is not int or interval < 60:
                            raise ValueError("InvalidStoredInterval")
                        previous = datetime.fromisoformat(r["next_run_utc"])
                        # Skip missed intervals instead of replaying old actions.
                        skips = max(1, int((now-previous).total_seconds()//interval)+1)
                        next_time = iso(previous + timedelta(seconds=skips*interval))
                except (ValueError, TypeError, OverflowError):
                    c.execute(
                        "UPDATE schedules SET enabled=0,last_status='error', "
                        "last_error='InvalidStoredWorkflow' WHERE id=?", (r["id"],))
                    continue
                if next_time is not None:
                    c.execute("UPDATE schedules SET next_run_utc=?,last_status='dispatch_pending',last_error='' WHERE id=?",
                              (next_time,r["id"]))
                else:
                    c.execute("UPDATE schedules SET enabled=0,last_status='dispatch_pending',last_error='' WHERE id=?",(r["id"],))
                dispatch_id = str(uuid4())
                c.execute("INSERT INTO schedule_runs(id,job_id,profile_id,started_utc,status) VALUES(?,?,?,?,?)",
                          (dispatch_id,r["id"],r["profile_id"],now_s,"dispatch_pending"))
                claimed.append(Job(id=r["id"],profile_id=r["profile_id"],workflow=workflow,
                                   next_run_utc=r["next_run_utc"],interval_seconds=interval,
                                   enabled=bool(interval),last_status="dispatch_pending",last_error="",
                                   dispatch_id=dispatch_id))
        return claimed

    @staticmethod
    def _safe_error(error: str) -> str:
        """Store exception *type* only; browser errors can expose page secrets."""
        name = str(error).partition(":")[0]
        return name[:80] if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,79}", name) else "AutomationError"

    @staticmethod
    def _is_latest(conn, job_id: str, dispatch_id: str) -> bool:
        row = conn.execute("SELECT id FROM schedule_runs WHERE job_id=? ORDER BY rowid DESC LIMIT 1",
                           (job_id,)).fetchone()
        return bool(row and row["id"] == dispatch_id)

    def record_dispatched(self, job_id: str, dispatch_id: str | None = None) -> None:
        """Accepted by browser manager != browser execution completed.

        Completion may race with this acknowledgement. Never overwrite a
        terminal run result with 'submitted'.
        """
        with self.store._connect() as c:
            if dispatch_id is not None:
                c.execute("UPDATE schedule_runs SET status='submitted' "
                          "WHERE id=? AND job_id=? AND status='dispatch_pending'",(dispatch_id,job_id))
                if not self._is_latest(c,job_id,dispatch_id):
                    return
                row = c.execute("SELECT status FROM schedule_runs WHERE id=?", (dispatch_id,)).fetchone()
                if row and row["status"] != "submitted":
                    return
            c.execute("UPDATE schedules SET last_status='submitted',last_error='' "
                      "WHERE id=? AND last_status='dispatch_pending'", (job_id,))

    def record_error(self, job_id: str, error: str, dispatch_id: str | None = None) -> None:
        """Failed browser submission; do not automatically replay side effects."""
        kind = self._safe_error(error)
        with self.store._connect() as c:
            if dispatch_id is None:
                latest = c.execute("SELECT id FROM schedule_runs WHERE job_id=? ORDER BY rowid DESC LIMIT 1",
                                   (job_id,)).fetchone()
                dispatch_id = latest["id"] if latest else None
            if dispatch_id:
                c.execute("UPDATE schedule_runs SET status='failed',finished_utc=?,error_type=? "
                          "WHERE id=? AND status IN ('dispatch_pending','submitted')",
                          (iso(utcnow()),kind,dispatch_id))
                if not self._is_latest(c,job_id,dispatch_id):
                    return
            c.execute("UPDATE schedules SET last_status='error',last_error=? WHERE id=?",
                      (kind,job_id))

    def record_completion(self, dispatch_id: str, status: str, error: str | None = None) -> None:
        """Terminal status from actual BrowserManager execution, not dispatch."""
        if status not in {"succeeded","failed","cancelled"}:
            raise ValueError("Nonterminal browser run status")
        kind = self._safe_error(error) if error else ""
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT job_id,status FROM schedule_runs WHERE id=?", (str(UUID(dispatch_id)),)).fetchone()
            if not row or row["status"] not in {"submitted","dispatch_pending"}:
                return
            c.execute("UPDATE schedule_runs SET status=?,error_type=?,finished_utc=? WHERE id=?",
                      (status,kind,iso(utcnow()),dispatch_id))
            if self._is_latest(c,row["job_id"],dispatch_id):
                c.execute("UPDATE schedules SET last_status=?,last_error=? WHERE id=?",
                          (status,kind,row["job_id"]))


    def retry_one_shot(self, job_id: str, now: datetime | None = None) -> None:
        """Re-arm failed/uncertain one-shots only after user confirmation.

        An uncertain dispatch might have started before the previous process
        died, so callers must explain the possible duplicate execution.
        """
        job_id = str(UUID(job_id))
        next_run = iso(now or utcnow())
        with self.store._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT enabled,interval_seconds,last_status FROM schedules WHERE id=?",
                            (job_id,)).fetchone()
            if row is None:
                raise KeyError("Schedule does not exist")
            if row["enabled"] or row["interval_seconds"] is not None or row["last_status"] not in {"error","dispatch_pending"}:
                raise ValueError("Only failed or uncertain one-time jobs can be retried")
            c.execute("UPDATE schedules SET enabled=1,next_run_utc=?,last_status='pending',last_error='' WHERE id=?",
                      (next_run,job_id))


class Scheduler:
    def __init__(self, store: ScheduleStore, dispatch: Callable[[str, dict | list], None],
                 *, interval=1.0, dispatch_job: Callable[[Job], None] | None = None):
        self.store = store
        self.dispatch = dispatch
        self.dispatch_job = dispatch_job
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
                        try:
                            if self.dispatch_job is not None:
                                self.dispatch_job(job)
                            else:
                                self.dispatch(job.profile_id, job.workflow)
                        except Exception as exc:
                            # Even unexpected callback errors must not kill the
                            # scheduler thread or automatically replay a job.
                            self.store.record_error(job.id, type(exc).__name__, job.dispatch_id)
                        else:
                            self.store.record_dispatched(job.id, job.dispatch_id)
                except (sqlite3.Error, ValueError, TypeError, OverflowError):
                    # Unexpected storage errors may be transient. Never kill the
                    # worker or auto-replay a previously claimed browser action.
                    pass
                self._stop.wait(self.interval)
        finally:
            self.store.store.close_thread_connection()
