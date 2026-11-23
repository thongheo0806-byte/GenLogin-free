"""Windows-safe batch journal regression: restarts, locks, privacy and crash states."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from autumn_genlogin.batch import BatchRunner
from autumn_genlogin.batch_history import BatchJournal
from autumn_genlogin.locks import ProfileBusyError
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store

from test_batch import FakeManager, eventually


class BatchHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # addCleanup executes LIFO: all daemon batch workers must close their
        # thread-local SQLite handles BEFORE deleting the Windows tempdir.
        self.addCleanup(self._await_workers)
        self.store=Store(Path(self.temp.name))
        self.profiles=[self.store.save(Profile(name=f"persistent-{i}")) for i in range(3)]
        self.ids=[p.id for p in self.profiles]
        self.flow=[{"action":"wait","seconds":0}]

    @staticmethod
    def _await_workers():
        for worker in threading.enumerate():
            if worker.name.startswith("autumn-batch-") and worker is not threading.current_thread():
                worker.join(timeout=6)
        leftovers = [worker.name for worker in threading.enumerate()
                     if worker.name.startswith("autumn-batch-")]
        if leftovers:
            raise AssertionError(f"Batch worker did not close: {leftovers!r}")

    def test_successful_batch_persists_across_new_runner_no_replay(self):
        original=BatchRunner(self.store,FakeManager(delay=0.08))
        ident=original.start(self.ids,self.flow,max_parallel=2)
        self.assertTrue(eventually(lambda:original.get(ident)["status"]=="succeeded"))
        other_manager=FakeManager()
        recovered=BatchRunner(Store(Path(self.temp.name)),other_manager)
        entry=recovered.get(ident)
        self.assertEqual(entry["status"],"succeeded")
        self.assertEqual(len(entry["items"]),3)
        self.assertEqual({x["status"] for x in entry["items"]},{"succeeded"})
        self.assertEqual(recovered.list()[0]["id"],ident)
        self.assertEqual(other_manager.launched,[])

    def test_orphan_running_is_uncertain_and_queued_never_replayed(self):
        journal=BatchJournal(self.store)
        ident=str(uuid4())
        journal.save({
            "id":ident,"created_utc":"2026-11-20T00:00:00+00:00",
            "finished_utc":None,"status":"running",
            "max_parallel":2,"cancel_requested":False,
            "items":[
                {"profile_id":self.ids[0],"status":"running","run_id":str(uuid4()),"error_type":""},
                {"profile_id":self.ids[1],"status":"submitting","run_id":None,"error_type":""},
                {"profile_id":self.ids[2],"status":"queued","run_id":None,"error_type":""},
            ],
        })
        manager=FakeManager()
        new_app=BatchRunner(Store(Path(self.temp.name)),manager)
        result=new_app.get(ident)
        self.assertEqual(result["status"],"partial")
        self.assertEqual([x["status"] for x in result["items"]],
                         ["uncertain","uncertain","cancelled"])
        self.assertEqual(result["items"][0]["error_type"],"InterruptedProcess")
        self.assertIsNotNone(result["finished_utc"])
        self.assertEqual(manager.launched,[])
        self.assertEqual(new_app.list()[0]["status"],"partial")
        with self.assertRaises(KeyError):
            new_app.cancel(ident)
        self.assertEqual(journal.get(ident)["status"],"partial")

    def test_second_process_style_reader_cannot_mark_live_owned_batch_dead(self):
        slow=FakeManager(delay=1.2)
        runner=BatchRunner(self.store,slow)
        ident=runner.start(self.ids[:1],self.flow,max_parallel=1)
        self.assertTrue(eventually(lambda:runner.get(ident)["items"][0]["status"]=="running"))
        another=BatchRunner(Store(Path(self.temp.name)),FakeManager())
        self.assertEqual(another.get(ident)["status"],"running")
        self.assertEqual(another.list()[0]["items"][0]["status"],"running")
        self.assertTrue(eventually(lambda:runner.get(ident)["status"]=="succeeded",timeout=6))
        self.assertEqual(another.get(ident)["status"],"succeeded")

    def test_cancelled_batch_stays_cancelled_after_restart(self):
        runner=BatchRunner(self.store,FakeManager(delay=1))
        ident=runner.start(self.ids,self.flow,max_parallel=1)
        self.assertTrue(eventually(lambda:runner.get(ident)["items"][0]["status"]=="running"))
        runner.cancel(ident)
        self.assertTrue(eventually(lambda:runner.get(ident)["status"]=="cancelled"))
        another=BatchRunner(Store(Path(self.temp.name)),FakeManager())
        self.assertEqual(another.get(ident)["status"],"cancelled")
        self.assertEqual([x["status"] for x in another.get(ident)["items"]],
                         ["cancelled"]*3)

    def test_workflow_secret_never_persisted_and_history_bounded(self):
        runner=BatchRunner(self.store,FakeManager(delay=0.02))
        secret="do-not-persist-browser-fill-data"
        ident=runner.start(self.ids[:1],
                           [{"action":"fill","selector":"#password","text":secret}],max_parallel=1)
        self.assertTrue(eventually(lambda:runner.get(ident)["status"]=="succeeded"))
        with self.store._connect() as conn:
            stored=conn.execute("SELECT snapshot_json FROM batch_history WHERE id=?",(ident,)).fetchone()[0]
        self.assertNotIn(secret,stored)
        self.assertNotIn("#password",stored)
        self.assertNotIn("workflow",stored)
        self.assertEqual(json.loads(stored)["id"],ident)
        # On Windows a completed result can be visible before the worker's
        # SQLite handle is closed. Wait for worker teardown before deleting
        # the temporary test database directory.
        self.assertTrue(runner.wait(ident,timeout=5))
        with self.assertRaises(ValueError):
            runner._journal.list(limit=101)

    def test_deleting_profile_refuses_active_batch_then_purges_audit(self):
        runner=BatchRunner(self.store,FakeManager(delay=0.5))
        ident=runner.start(self.ids,self.flow,max_parallel=1)
        self.assertTrue(eventually(lambda:runner.get(ident)["items"][0]["status"]=="running"))
        with self.assertRaises(ProfileBusyError):
            self.store.delete(self.ids[2]) # queued profile has no browser lock
        self.assertIsNotNone(self.store.get(self.ids[2]))
        runner.cancel(ident)
        self.assertTrue(eventually(lambda:runner.get(ident)["status"]=="cancelled"))
        self.store.delete(self.ids[2])
        with self.assertRaises(KeyError):
            runner._journal.get(ident)
        self.assertEqual(self.store.all().__len__(),2)

    def test_history_list_uses_one_read_and_no_terminal_os_lease(self):
        journal=BatchJournal(self.store)
        created=[]
        for i in range(32):
            ident=str(uuid4())
            created.append(ident)
            journal.save({
                "id":ident,"created_utc":"2026-11-20T00:00:00+00:00",
                "finished_utc":"2026-11-20T00:00:01+00:00",
                "status":"succeeded","max_parallel":1,"cancel_requested":False,
                "items":[{"profile_id":self.ids[0],"status":"succeeded",
                          "run_id":str(uuid4()),"error_type":""}],
            })
        # A full terminal-history list must not call get 32 times or acquire
        # any ProfileLease merely because the GUI lists completed work.
        with (patch.object(journal,"get",side_effect=AssertionError("N+1 get")),
              patch("autumn_genlogin.batch_history.ProfileLease",
                    side_effect=AssertionError("Terminal history must not lock"))):
            recent=journal.list(limit=32)
        self.assertEqual([x["id"] for x in recent],list(reversed(created)))
        self.assertTrue(all(x["status"]=="succeeded" for x in recent))
        recent[0]["items"][0]["status"]="failed"
        self.assertEqual(journal.get(created[-1])["items"][0]["status"],
                         "succeeded","List results must be detached snapshots")

    def test_history_list_recovers_only_running_entry(self):
        journal=BatchJournal(self.store)
        ended=str(uuid4())
        active=str(uuid4())
        item={"profile_id":self.ids[0],"status":"succeeded",
              "run_id":str(uuid4()),"error_type":""}
        journal.save({
            "id":ended,"created_utc":"2026-11-20T00:00:00+00:00",
            "finished_utc":"2026-11-20T00:00:01+00:00",
            "status":"succeeded","max_parallel":1,"cancel_requested":False,
            "items":[item],
        })
        journal.save({
            "id":active,"created_utc":"2026-11-20T00:00:00+00:00",
            "finished_utc":None,"status":"running","max_parallel":1,
            "cancel_requested":False,
            "items":[{**item,"status":"running"}],
        })
        with patch.object(journal,"_recover",wraps=journal._recover) as recover:
            snapshot=journal.list(limit=2)
        self.assertEqual(recover.call_count,1)
        self.assertEqual(recover.call_args.args[0]["id"],active)
        self.assertEqual([x["status"] for x in snapshot],["partial","succeeded"])
        self.assertEqual(snapshot[0]["items"][0]["status"],"uncertain")
        # No browser manager was invoked, and uncertain work was not replayed.
        self.assertEqual(journal.get(active)["status"],"partial")

    def test_bad_initial_disk_write_stops_all_browser_launches(self):
        manager=FakeManager()
        runner=BatchRunner(self.store,manager)
        with patch.object(runner._journal,"save",side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                runner.start(self.ids,self.flow,max_parallel=2)
        self.assertEqual(manager.launched,[])
        self.assertEqual(runner._leases,{})
        self.assertEqual(runner._batches,{})
        self.assertEqual(runner.list(),[])

    def test_history_bounded_to_last_hundred_finished_batches(self):
        journal=BatchJournal(self.store)
        first_id=None
        for index in range(103):
            ident=str(uuid4())
            if first_id is None:first_id=ident
            journal.save({
                "id":ident,"created_utc":"2026-11-20T00:00:00+00:00",
                "finished_utc":"2026-11-20T00:00:01+00:00",
                "status":"succeeded","max_parallel":1,"cancel_requested":False,
                "items":[{"profile_id":self.ids[0],"status":"succeeded",
                          "run_id":str(uuid4()),"error_type":""}],
            })
        self.assertEqual(len(journal.list(limit=100)),100)
        with self.assertRaises(KeyError):
            journal.get(first_id)


if __name__=="__main__":
    unittest.main()
