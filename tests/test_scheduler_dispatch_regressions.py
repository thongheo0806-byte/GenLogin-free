"""Regression tests for crash-safe scheduler submission state and opt-in retries.

Dispatch is not a completion acknowledgement. Automatic replay of an uncertain
one-shot may duplicate account actions, so this is explicitly user-controlled.
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from autumn_genlogin.models import Profile
from autumn_genlogin.scheduler import ScheduleStore, Scheduler
from autumn_genlogin.storage import Store


class SchedulerDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))
        self.profile = self.store.save(Profile(name="Schedule regression"))
        self.schedules = ScheduleStore(self.store)
        self.workflow = [{"action": "wait", "seconds": 0}]

    def due_once(self):
        return self.schedules.add(
            self.profile.id, self.workflow,
            datetime.now(timezone.utc) - timedelta(minutes=1),
        )

    def status(self, job_id):
        return next(job for job in self.schedules.list() if job.id == job_id)

    def test_unacknowledged_claim_survives_restart_without_auto_replay(self):
        job_id = self.due_once()
        claimed = self.schedules.claim_due()
        self.assertEqual([job.id for job in claimed], [job_id])
        self.assertEqual(self.status(job_id).last_status, "dispatch_pending")
        self.assertFalse(self.status(job_id).enabled)

        # A fresh instance after an unclean exit must not silently run it twice.
        restarted = ScheduleStore(Store(Path(self.tmp.name)))
        self.assertEqual(restarted.claim_due(), [])
        persisted = next(job for job in restarted.list() if job.id == job_id)
        self.assertEqual(persisted.last_status, "dispatch_pending")
        self.assertFalse(persisted.enabled)

    def test_acknowledge_means_submitted_not_completed(self):
        job_id = self.due_once()
        self.schedules.claim_due()
        self.schedules.record_dispatched(job_id)
        self.assertEqual(self.status(job_id).last_status, "submitted")
        with self.assertRaises(ValueError):
            self.schedules.retry_one_shot(job_id)

    def test_failed_one_shot_requires_explicit_retry(self):
        job_id = self.due_once()
        self.schedules.claim_due()
        self.schedules.record_error(job_id, "synthetic dispatch rejected")
        self.assertFalse(self.status(job_id).enabled)
        self.assertEqual(self.schedules.claim_due(), [])
        self.assertEqual(self.status(job_id).last_status, "error")
        self.schedules.retry_one_shot(job_id)
        self.assertTrue(self.status(job_id).enabled)
        self.assertEqual(self.status(job_id).last_status, "pending")
        self.assertEqual(self.status(job_id).last_error, "")
        self.assertEqual([job.id for job in self.schedules.claim_due()], [job_id])

    def test_uncertain_one_shot_manual_retry_and_repeating_job_rejected(self):
        uncertain = self.due_once()
        self.schedules.claim_due()
        self.schedules.retry_one_shot(uncertain)
        self.assertTrue(self.status(uncertain).enabled)
        repeating = self.schedules.add(
            self.profile.id, self.workflow,
            datetime.now(timezone.utc) - timedelta(minutes=1), 60,
        )
        self.schedules.claim_due()
        self.schedules.record_error(repeating, "busy")
        with self.assertRaises(ValueError):
            self.schedules.retry_one_shot(repeating)
        with self.assertRaises(KeyError):
            self.schedules.retry_one_shot(str(uuid4()))

    def test_worker_records_exception_instead_of_dying_or_replaying(self):
        job_id = self.due_once()
        entered = threading.Event()

        def reject(_pid, _workflow):
            entered.set()
            raise AssertionError("synthetic failure")

        worker = Scheduler(self.schedules, reject, interval=0.01)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
        finally:
            worker.stop()
        job = self.status(job_id)
        self.assertEqual(job.last_status, "error")
        self.assertFalse(job.enabled)
        self.assertEqual(self.schedules.claim_due(), [])

    def test_worker_acknowledges_only_browser_manager_acceptance(self):
        job_id = self.due_once()
        entered = threading.Event()

        def accept(_pid, _workflow):
            entered.set()

        worker = Scheduler(self.schedules, accept, interval=0.01)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
        finally:
            worker.stop()
        self.assertEqual(self.status(job_id).last_status, "submitted")
        self.assertFalse(self.status(job_id).enabled)


if __name__ == "__main__":
    unittest.main()
