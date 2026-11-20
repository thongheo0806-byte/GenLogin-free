"""Durable scheduled automation result journal and crash-state regressions.

The run journal records IDs, timestamps and states only. It must never persist
extracted page text, secrets or raw browser stack traces.
"""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autumn_genlogin.models import Profile
from autumn_genlogin.scheduler import ScheduleStore, Scheduler
from autumn_genlogin.storage import Store


class ScheduleJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))
        self.profile = self.store.save(Profile(name="Journal"))
        self.journal = ScheduleStore(self.store)
        self.workflow = [{"action": "wait", "seconds": 0}]

    def due(self, interval=None):
        return self.journal.add(self.profile.id, self.workflow,
                                datetime.now(timezone.utc) - timedelta(minutes=2), interval)

    def test_claim_history_persists_across_process_like_restart(self):
        job_id = self.due()
        [job] = self.journal.claim_due()
        self.assertEqual(job.id, job_id)
        self.assertIsNotNone(job.dispatch_id)
        self.assertEqual(self.journal.history(job_id)[0].status, "dispatch_pending")
        fresh = ScheduleStore(Store(Path(self.tmp.name)))
        self.assertEqual(fresh.claim_due(), [])
        self.assertEqual(fresh.history(job_id)[0].id, job.dispatch_id)
        self.assertIsNone(fresh.history(job_id)[0].finished_utc)

    def test_acknowledge_then_success_is_real_terminal_state(self):
        job_id = self.due()
        [job] = self.journal.claim_due()
        self.journal.record_dispatched(job_id, job.dispatch_id)
        self.assertEqual(self.journal.history(job_id)[0].status, "submitted")
        self.assertIsNone(self.journal.history(job_id)[0].finished_utc)
        self.journal.record_completion(job.dispatch_id, "succeeded")
        self.assertEqual(self.journal.history(job_id)[0].status, "succeeded")
        self.assertIsNotNone(self.journal.history(job_id)[0].finished_utc)
        self.assertEqual(self.journal.list()[0].last_status, "succeeded")

    def test_immediate_completion_race_cannot_regress_to_submitted(self):
        job_id = self.due()
        [job] = self.journal.claim_due()
        self.journal.record_completion(job.dispatch_id, "succeeded")
        self.journal.record_dispatched(job_id, job.dispatch_id)
        self.assertEqual(self.journal.history()[0].status, "succeeded")
        self.assertEqual(self.journal.list()[0].last_status, "succeeded")

    def test_cancellation_and_failure_are_final_and_secret_free(self):
        job_id = self.due()
        [job] = self.journal.claim_due()
        self.journal.record_completion(job.dispatch_id, "failed", "TimeoutError: secret-cookie-value")
        entry = self.journal.history()[0]
        self.assertEqual(entry.error_type, "TimeoutError")
        self.assertEqual(entry.status, "failed")
        self.assertNotIn("secret",repr(entry))
        self.journal.record_completion(job.dispatch_id, "succeeded")
        self.assertEqual(self.journal.history()[0].status, "failed")
        with self.assertRaises(ValueError):
            self.journal.record_completion(job.dispatch_id, "running")
        self.assertFalse(self.journal.list()[0].enabled)

    def test_dispatch_exception_class_is_stored_not_exception_contents(self):
        job_id = self.due()
        [job] = self.journal.claim_due()
        self.journal.record_error(job_id, "RuntimeError: private URL /?token=secret", job.dispatch_id)
        entry = self.journal.history()[0]
        self.assertEqual((entry.status, entry.error_type), ("failed", "RuntimeError"))
        self.assertEqual(self.journal.list()[0].last_status,"error")
        self.assertNotIn("secret",str(entry))

    def test_newer_interval_result_wins_over_old_late_completion(self):
        job_id = self.due(interval=60)
        [old] = self.journal.claim_due()
        self.journal.record_dispatched(job_id, old.dispatch_id)
        now = datetime.now(timezone.utc) + timedelta(minutes=2)
        [new] = self.journal.claim_due(now)
        self.journal.record_dispatched(job_id, new.dispatch_id)
        self.journal.record_completion(new.dispatch_id, "succeeded")
        self.journal.record_completion(old.dispatch_id, "failed", "RuntimeError: prior")
        self.assertEqual(self.journal.list()[0].last_status,"succeeded")
        statuses={r.id:r.status for r in self.journal.history(job_id)}
        self.assertEqual(statuses[old.dispatch_id],"failed")
        self.assertEqual(statuses[new.dispatch_id],"succeeded")

    def test_scheduler_completion_callback_and_reopen(self):
        job_id=self.due()
        finished=threading.Event()
        def receive(job):
            self.journal.record_completion(job.dispatch_id,"succeeded")
            finished.set()
        worker=Scheduler(self.journal,lambda _pid,_flow: None,
                         dispatch_job=receive,interval=0.01)
        worker.start()
        try:
            self.assertTrue(finished.wait(5))
        finally:
            worker.stop()
        self.assertEqual(self.journal.history(job_id)[0].status,"succeeded")
        self.assertEqual(self.journal.list()[0].last_status,"succeeded")

    def test_remove_schedule_erases_all_its_run_history(self):
        job_id=self.due()
        self.journal.claim_due()
        self.journal.remove(job_id)
        self.assertEqual(self.journal.history(job_id),[])

    def test_delete_profile_erases_run_history_inside_profile_transaction(self):
        job_id=self.due()
        self.journal.claim_due()
        self.store.delete(self.profile.id)
        self.assertEqual(self.journal.history(job_id),[])
        self.assertEqual(self.journal.list(),[])

    def test_history_bounded_pagination_arguments(self):
        self.due()
        with self.assertRaises(ValueError):
            self.journal.history(limit=0)
        with self.assertRaises(ValueError):
            self.journal.history(limit=201)
        with self.assertRaises(ValueError):
            self.journal.history(job_id="../relative")
        self.assertEqual(self.journal.history(),[])


if __name__ == "__main__":
    unittest.main()
