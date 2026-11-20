"""Batch orchestration validation, per-profile isolation and cancellation.

Synthetic manager callbacks keep tests deterministic; the separate Windows
Chromium lane checks real SharedBrowserManager lifecycle.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from uuid import uuid4

from autumn_genlogin.batch import BatchRunner
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


def eventually(predicate, timeout=6):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate(): return True
        time.sleep(0.02)
    return False


class FakeManager:
    MAX_BROWSERS=6
    def __init__(self, *, delay=0.05, reject=None):
        self.delay=delay
        self.reject=reject
        self.lock=threading.RLock()
        self.running={}
        self.max_seen=0
        self.launched=[]
        self.cancellations=[]

    def active(self, pid):
        with self.lock: return pid in self.running

    def last_run(self,pid):
        with self.lock:
            return {"id":self.running[pid][0]} if pid in self.running else None

    def start_workflow(self,pid,workflow,*,on_finish=None,run_id=None):
        if pid==self.reject: raise RuntimeError("reject-not-secret")
        runid=str(uuid4())
        with self.lock:
            if pid in self.running: raise ValueError("already running")
            self.running[pid]=(runid,on_finish)
            self.launched.append((pid,workflow))
            self.max_seen=max(self.max_seen,len(self.running))

        def complete():
            with self.lock:
                running=self.running.pop(pid,None)
            if running and running[1]:running[1]("succeeded",None)
        t=threading.Timer(self.delay,complete)
        t.daemon=True
        t.start()
        return runid

    def cancel(self,pid):
        with self.lock:
            running=self.running.pop(pid,None)
            self.cancellations.append(pid)
        if running and running[1]: running[1]("cancelled",None)


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name))
        self.profiles=[self.store.save(Profile(name=f"batch {i}")) for i in range(5)]
        self.ids=[p.id for p in self.profiles]
        self.workflow=[{"action":"wait","seconds":0}]

    def test_multi_profile_parallelism_bounded_and_completion(self):
        manager=FakeManager(delay=0.08)
        runner=BatchRunner(self.store,manager)
        batch_id=runner.start(self.ids,self.workflow,max_parallel=2)
        self.assertTrue(eventually(lambda:runner.get(batch_id)["status"]=="succeeded"))
        result=runner.get(batch_id)
        self.assertEqual(len(manager.launched),5)
        self.assertLessEqual(manager.max_seen,2)
        self.assertEqual(len(set(pid for pid,_ in manager.launched)),5)
        self.assertEqual({item["status"] for item in result["items"]},{"succeeded"})
        self.assertIsNotNone(result["finished_utc"])

    def test_validation_is_atomic_and_no_browser_launch(self):
        manager=FakeManager()
        runner=BatchRunner(self.store,manager)
        invalid_cases=[
            ([],self.workflow,1),
            (self.ids+[self.ids[0]],self.workflow,1),
            (self.ids,[{"action":"python","source":"print(1)"}],1),
            (self.ids,self.workflow,7),
            ([str(uuid4())],self.workflow,1),
            (["../escape"],self.workflow,1),
        ]
        for ids,flow,parallel in invalid_cases:
            with self.subTest(ids=ids[:2],parallel=parallel):
                with self.assertRaises((ValueError,TypeError,KeyError)):
                    runner.start(ids,flow,max_parallel=parallel)
        self.assertEqual(manager.launched,[])
        self.assertEqual(runner.list(),[])

    def test_one_profile_launch_failure_only_marks_its_item(self):
        manager=FakeManager(reject=self.ids[2])
        runner=BatchRunner(self.store,manager)
        key=runner.start(self.ids,self.workflow,max_parallel=3)
        self.assertTrue(eventually(lambda:runner.get(key)["status"]=="partial"))
        entry=runner.get(key)
        failures=[i for i in entry["items"] if i["status"]=="failed"]
        self.assertEqual(len(failures),1)
        self.assertEqual(failures[0]["profile_id"],self.ids[2])
        self.assertEqual(failures[0]["error_type"],"RuntimeError")
        self.assertNotIn("reject-not-secret",repr(entry))

    def test_cancel_does_not_launch_queue_or_cancel_someone_else(self):
        manager=FakeManager(delay=0.8)
        runner=BatchRunner(self.store,manager)
        key=runner.start(self.ids,self.workflow,max_parallel=1)
        self.assertTrue(eventually(lambda:any(i["status"]=="running" for i in runner.get(key)["items"])))
        runner.cancel(key)
        self.assertTrue(eventually(lambda:runner.get(key)["status"] in {"cancelled","partial"}))
        self.assertEqual(len(manager.launched),1)
        self.assertEqual([i["status"] for i in runner.get(key)["items"]].count("cancelled"),5)
        self.assertEqual(len(manager.cancellations),1)

    def test_redacts_workflow_values_and_does_not_keep_payload(self):
        manager=FakeManager()
        runner=BatchRunner(self.store,manager)
        secret="fake-sensitive-input"
        payload=[{"action":"fill","selector":"#input","text":secret}]
        key=runner.start(self.ids[:1],payload)
        self.assertTrue(eventually(lambda:runner.get(key)["status"]=="succeeded"))
        self.assertNotIn(secret,json.dumps(runner.get(key)))

    def test_bad_batch_id_and_list_limit(self):
        runner=BatchRunner(self.store,FakeManager())
        with self.assertRaises(KeyError):runner.get(str(uuid4()))
        with self.assertRaises(ValueError):runner.list(limit=31)
        with self.assertRaises(ValueError):runner.get("../foo")


if __name__=="__main__":
    unittest.main()
