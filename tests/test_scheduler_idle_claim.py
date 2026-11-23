"""Scheduler read-first polling must retain cross-thread atomic dispatch."""
from __future__ import annotations

import concurrent.futures
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autumn_genlogin.models import Profile
from autumn_genlogin.scheduler import ScheduleStore
from autumn_genlogin.storage import Store


class SchedulerPollTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name), reuse_connections=True)
        self.addCleanup(self.store.close_thread_connection)
        self.profile = self.store.save(Profile(name="Synthetic polling fixture"))
        self.schedules = ScheduleStore(self.store)
        self.workflow = [{"action": "wait", "seconds": 0}]

    def test_idle_poll_never_requests_immediate_write_transaction(self):
        commands = []
        with self.store._connect() as conn:
            conn.set_trace_callback(commands.append)
        try:
            for _ in range(8):
                self.assertEqual(self.schedules.claim_due(), [])
            self.assertFalse(any("BEGIN IMMEDIATE" in q.upper() for q in commands))
            self.assertTrue(any("SELECT 1 FROM SCHEDULES" in q.upper() for q in commands))
            job = self.schedules.add(
                self.profile.id, self.workflow,
                datetime.now(timezone.utc) - timedelta(minutes=1),
            )
            commands.clear()
            self.assertEqual([j.id for j in self.schedules.claim_due()], [job])
            self.assertTrue(any("BEGIN IMMEDIATE" in q.upper() for q in commands))
        finally:
            with self.store._connect() as conn:
                conn.set_trace_callback(None)

    def test_concurrent_claims_submit_same_one_shot_only_once(self):
        job = self.schedules.add(
            self.profile.id, self.workflow,
            datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        # Independently owned thread SQLite handles compete in a real WAL DB.
        def claim(_):
            try:
                return [j.id for j in self.schedules.claim_due()]
            finally:
                self.store.close_thread_connection()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            batches = list(pool.map(claim, range(16)))
        claimed = [ident for group in batches for ident in group]
        self.assertEqual(claimed, [job])
        self.assertEqual(self.schedules.claim_due(), [])
        self.assertEqual(len(self.schedules.history(job)), 1)
        entry = next(j for j in self.schedules.list() if j.id == job)
        self.assertFalse(entry.enabled)


if __name__ == "__main__":
    unittest.main()
