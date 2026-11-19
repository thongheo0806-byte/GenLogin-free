"""Tests that exercise real graph execution, SQLite job claiming and engine flags."""
from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autumn_genlogin.graph import steps_to_graph, validate_graph, execute_graph
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store
from autumn_genlogin.scheduler import ScheduleStore, Scheduler
from autumn_genlogin.engines import browser_options, ENGINE_CAPABILITIES


class GraphTests(unittest.TestCase):
    def test_sequence_compiles_and_executes(self):
        steps=[{"action":"goto","url":"https://example.com"},{"action":"click","selector":"button"}]
        graph=steps_to_graph(steps)
        seen=[]
        async def action(step):seen.append(step)
        async def exists(selector):return False
        result=asyncio.run(execute_graph(graph,action=action,exists=exists))
        self.assertEqual(seen,steps)
        self.assertEqual(result["status"],"succeeded")

    def test_conditions_and_repeats(self):
        nodes=[{"id":"start","type":"start"},{"id":"cycle","type":"repeat","times":3},
               {"id":"work","type":"action","step":{"action":"wait","seconds":0}},
               {"id":"branch","type":"condition","selector":"h1"},
               {"id":"end","type":"end"}]
        edges=[{"from":"start","to":"cycle","branch":"next"},
               {"from":"cycle","to":"work","branch":"yes"},
               {"from":"cycle","to":"branch","branch":"no"},
               {"from":"work","to":"cycle","branch":"next"},
               {"from":"branch","to":"end","branch":"yes"},
               {"from":"branch","to":"end","branch":"no"}]
        graph=validate_graph({"format":"AutumnGenLogin/graph-1","nodes":nodes,"edges":edges})
        called=[]
        async def action(step):called.append(step)
        async def exists(selector):return True
        result=asyncio.run(execute_graph(graph,action=action,exists=exists))
        self.assertEqual(len(called),3)
        self.assertEqual(result["status"],"succeeded")

    def test_invalid_missing_branch_rejected(self):
        graph=steps_to_graph([{"action":"screenshot"}])
        graph["edges"].pop()
        with self.assertRaises(ValueError):validate_graph(graph)

    def test_limit_stops_unbounded_cycle_without_hanging(self):
        graph=steps_to_graph([{"action":"wait","seconds":0}])
        graph["edges"][-1]["to"]="step_1"
        with self.assertRaises(ValueError):
            validate_graph(graph)

    def test_cancellation(self):
        graph=steps_to_graph([{"action":"wait","seconds":0}])
        async def action(step):pass
        async def exists(selector):return False
        result=asyncio.run(execute_graph(graph,action=action,exists=exists,cancelled=lambda:True))
        self.assertEqual(result["status"],"cancelled")


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name))
        self.profile=self.store.save(Profile(name="Scheduled"))
        self.schedules=ScheduleStore(self.store)
        self.workflow=[{"action":"wait","seconds":0}]

    def test_one_shot_atomic_claim_and_disable(self):
        job=self.schedules.add(self.profile.id,self.workflow,datetime.now(timezone.utc)-timedelta(minutes=1))
        claimed=self.schedules.claim_due()
        self.assertEqual([x.id for x in claimed],[job])
        self.assertEqual(self.schedules.claim_due(),[])
        self.assertFalse(self.schedules.list()[0].enabled)

    def test_repeat_advances_past_missed_intervals(self):
        now=datetime.now(timezone.utc)
        self.schedules.add(self.profile.id,self.workflow,now-timedelta(days=2),interval_seconds=60)
        self.schedules.claim_due(now)
        upcoming=datetime.fromisoformat(self.schedules.list()[0].next_run_utc)
        self.assertGreater(upcoming,now)
        self.assertLess((upcoming-now).total_seconds(),61)

    def test_scheduler_dispatches_and_does_not_refire(self):
        dispatched=[]
        self.schedules.add(self.profile.id,self.workflow,datetime.now(timezone.utc)-timedelta(seconds=5))
        scheduler=Scheduler(self.schedules,lambda pid,flow:dispatched.append((pid,flow)),interval=0.05)
        scheduler.start()
        threading.Event().wait(0.25)
        scheduler.stop()
        self.assertEqual(dispatched,[(self.profile.id,self.workflow)])

    def test_bad_workflow_and_naive_time_rejected(self):
        with self.assertRaises(ValueError):self.schedules.add(self.profile.id,[],datetime.now(timezone.utc))
        with self.assertRaises(ValueError):self.schedules.add(self.profile.id,self.workflow,datetime.now())

    def test_store_can_reuse_thread_connection_and_close(self):
        self.store.close_thread_connection()
        pooled=Store(Path(self.tmp.name),reuse_connections=True)
        with pooled._connect() as c: first=c
        with pooled._connect() as c: self.assertIs(c,first)
        pooled.close_thread_connection()
        with pooled._connect() as c: self.assertIsNot(c,first)
        pooled.close_thread_connection()


class EngineTests(unittest.TestCase):
    def test_all_engines_are_real_playwright_types(self):
        for name,props in ENGINE_CAPABILITIES.items():
            engine,opts=browser_options(Profile(browser=name),"/tmp/profile",headless=True)
            self.assertIn(engine,{"chromium","firefox","webkit"})
            self.assertTrue(opts["headless"])

    def test_extension_rejected_for_nonchromium(self):
        for name in ("chrome","msedge","firefox","webkit"):
            with self.assertRaises(ValueError):
                browser_options(Profile(browser=name),"/tmp/profile",headless=True,extension_paths=["/tmp/extension"])

    def test_ipv6_proxy_is_bracketed(self):
        p=Profile(browser="webkit",proxy_scheme="http",proxy_host="::1",proxy_port=8000)
        kind,opts=browser_options(p,"/tmp/p",headless=True)
        self.assertEqual(opts["proxy"]["server"],"http://[::1]:8000")


if __name__=="__main__":unittest.main()
