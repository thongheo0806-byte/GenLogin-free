"""Durable, sanitized history for local batch automation.

Only profile UUIDs, run UUIDs, timing, statuses and safe error *types* are
stored. Workflow definitions, browser responses, credentials and extracted
values must never enter SQLite.

A per-batch OS lease distinguishes a still-running batch in another process
from an orphaned batch after an unclean shutdown. Orphans are never replayed.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import re
from uuid import UUID

from .locks import ProfileBusyError, ProfileLease


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BatchJournal:
    HISTORY_LIMIT = 100
    ACTIVE = frozenset({"running", "submitting", "queued"})
    ITEM_TERMINAL = frozenset({"succeeded", "failed", "cancelled", "uncertain"})
    BATCH_TERMINAL = frozenset({"succeeded", "partial", "cancelled"})

    def __init__(self, store):
        self.store = store
        with store._connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS batch_history (
                id TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL,
                created_utc TEXT NOT NULL
            )""")

    @staticmethod
    def _sanitized(batch: dict) -> dict:
        def uuid_or_none(value):
            try:
                return str(UUID(value)) if isinstance(value, str) else None
            except (ValueError, TypeError, AttributeError):
                return None

        ident = uuid_or_none(batch.get("id"))
        if ident is None:
            raise ValueError("Invalid batch ID")
        items = []
        for item in batch["items"]:
            pid = uuid_or_none(item["profile_id"])
            if pid is None or item["status"] not in (BatchJournal.ACTIVE | BatchJournal.ITEM_TERMINAL):
                raise ValueError("Invalid batch history item")
            error = str(item.get("error_type") or "")
            if error and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,79}",error):
                error = "AutomationError"
            items.append({
                "profile_id":pid,
                "status":item["status"],
                "run_id":uuid_or_none(item.get("run_id")),
                "error_type":error,
            })
        if batch.get("status") not in {"running"} | BatchJournal.BATCH_TERMINAL:
            raise ValueError("Invalid batch history status")
        return {
            "id":ident,
            "created_utc":str(batch["created_utc"])[:40],
            "finished_utc":str(batch["finished_utc"])[:40] if batch.get("finished_utc") else None,
            "status":batch["status"],
            "max_parallel":int(batch["max_parallel"]),
            "cancel_requested":bool(batch["cancel_requested"]),
            "items":items,
        }

    def save(self, batch: dict) -> None:
        safe = self._sanitized(batch)
        payload = json.dumps(safe, separators=(",", ":"),ensure_ascii=True)
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO batch_history(id,snapshot_json,created_utc) VALUES (?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET snapshot_json=excluded.snapshot_json",
                (safe["id"],payload,safe["created_utc"]),
            )

    def _recover(self, snapshot: dict) -> dict:
        """Distinguish an unowned crash from a live batch in another instance."""
        if snapshot["status"] != "running":
            return snapshot
        # Do not rely on PID checks: OS-backed leases survive neither process
        # death nor a normal close and cannot be fooled by recycled PIDs.
        try:
            with ProfileLease(self.store.base,snapshot["id"]):
                # Re-read after acquiring the lock, before mutating the row.
                with self.store._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute("SELECT snapshot_json FROM batch_history WHERE id=?",
                                       (snapshot["id"],)).fetchone()
                    if row is None:
                        raise KeyError("Batch not found")
                    current = json.loads(row["snapshot_json"])
                    if current["status"] != "running":
                        return current
                    for item in current["items"]:
                        if item["status"] in {"running","submitting"}:
                            item["status"] = "uncertain"
                            item["error_type"] = "InterruptedProcess"
                        elif item["status"] == "queued":
                            # This item was never marked as submitted to browser.
                            item["status"] = "cancelled"
                    current["status"] = ("partial" if any(item["status"] in
                        {"failed","uncertain"} for item in current["items"]) else "cancelled")
                    current["finished_utc"] = _utc()
                    conn.execute("UPDATE batch_history SET snapshot_json=? WHERE id=?",
                                 (json.dumps(current,separators=(",", ":")),current["id"]))
                    return current
        except ProfileBusyError:
            # An independent process still owns this batch: do not mark it dead.
            return snapshot

    def get(self, batch_id: str) -> dict:
        ident=str(UUID(batch_id))
        with self.store._connect() as conn:
            row=conn.execute("SELECT snapshot_json FROM batch_history WHERE id=?",(ident,)).fetchone()
        if row is None:
            raise KeyError("Batch not found")
        return deepcopy(self._recover(json.loads(row["snapshot_json"])))

    def list(self, limit: int = 20) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= self.HISTORY_LIMIT:
            raise ValueError("History limit must be 1-100")
        with self.store._connect() as conn:
            keys=[row["id"] for row in conn.execute(
                "SELECT id FROM batch_history ORDER BY rowid DESC LIMIT ?",(limit,)).fetchall()]
        return [self.get(ident) for ident in keys]
