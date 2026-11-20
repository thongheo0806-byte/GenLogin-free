"""Real Playwright integration: shared driver, graph, recorder, manual window close.

Requires AUTUMN_E2E=1 and Playwright-managed browser binaries. No public
services, anti-abuse sites, or real user data involved.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store
from autumn_genlogin.browser_shared import SharedBrowserManager
from autumn_genlogin.graph import steps_to_graph


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        data=(b'<html><body><h1 id="title">Autumn test</h1>'
              b'<input id="secret" value="" />'
              b'<select id="category"><option value="">none</option><option value="sensitive-unique-option">sensitive</option></select>'
              b'<button id="press">Push</button>'
              b'<script>document.querySelector("#press").onclick=()=>{document.body.dataset.clicked="yes"}</script>'
              b'</body></html>')
        self.send_response(200)
        self.send_header("Content-Type","text/html")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self,*args):pass


def eventually(predicate,timeout=25):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        if predicate():return True
        time.sleep(0.1)
    return False


@unittest.skipUnless(os.environ.get("AUTUMN_E2E")=="1", "requires Playwright browser binaries")
class SharedBrowserRealTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name))
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Fixture)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.origin=f"http://127.0.0.1:{self.server.server_port}"
        self.manager=SharedBrowserManager(self.store,headless=True)

    def tearDown(self):
        self.manager.stop_all()
        self.assertTrue(eventually(lambda:self.manager.count()==0,timeout=20),
                        "Browser sessions did not close and release locks")
        self.manager.close_driver()
        self.server.shutdown();self.server.server_close()
        self.thread.join(timeout=5)
        # Chromium can still be releasing WebStorage files on Windows after
        # the transport shuts down. Retry only the filesystem cleanup; fail
        # explicitly if locks persist. Never silently ignore leaked sessions.
        for attempt in range(25):
            try:
                self.tmp.cleanup()
                break
            except PermissionError:
                if attempt == 24: raise
                time.sleep(0.2)

    def test_two_profiles_share_one_driver_and_graph_executes(self):
        profiles=[]
        for name in ("one","two"):
            profiles.append(self.store.save(Profile(name=name,browser="chromium",start_url=self.origin)))
        self.manager.start(profiles[0].id)
        self.manager.start(profiles[1].id)
        self.assertTrue(eventually(lambda:any(x[1:]==("status","Running") for x in list(self.manager.events.queue))))
        self.assertTrue(eventually(lambda:all(self.manager._sessions[p.id].ready.is_set() for p in profiles)))
        self.assertEqual(self.manager.count(),2)
        # One Python/Node Playwright driver, independent persistent contexts.
        self.assertIsNotNone(self.manager._playwright)
        self.assertTrue(self.manager._thread.is_alive())
        self.manager.run_graph(profiles[0].id,steps_to_graph([{"action":"extract_text","selector":"#title"}]))
        self.assertTrue(eventually(lambda:(self.manager.last_run(profiles[0].id) or {}).get("status")=="succeeded"))
        self.assertEqual(self.manager.last_run(profiles[0].id)["extracted"][0]["text"],"Autumn test")
        self.assertIsNone(self.manager.last_run(profiles[1].id))
        self.manager.stop(profiles[0].id)
        self.assertTrue(eventually(lambda:not self.manager.active(profiles[0].id)))
        self.assertTrue(self.manager.active(profiles[1].id))

    def test_scheduled_run_records_real_browser_execution(self):
        """Real browser automation acknowledges completion through the journal."""
        from datetime import datetime, timedelta, timezone
        from autumn_genlogin.scheduler import ScheduleStore, Scheduler

        profile = self.store.save(Profile(name="scheduled", browser="chromium",start_url=self.origin))
        schedules = ScheduleStore(self.store)
        job_id = schedules.add(profile.id,
            [{"action":"wait_for","selector":"#title"},{"action":"extract_text","selector":"#title"}],
            datetime.now(timezone.utc)-timedelta(minutes=1))

        def dispatch_job(job):
            self.manager.start_workflow(
                job.profile_id, job.workflow, run_id=job.dispatch_id,
                on_finish=lambda status,error,ident=job.dispatch_id:
                    schedules.record_completion(ident,status,error))

        scheduler = Scheduler(schedules,self.manager.start_workflow,
                              dispatch_job=dispatch_job,interval=0.05)
        scheduler.start()
        try:
            self.assertTrue(eventually(lambda:
                bool(schedules.history(job_id)) and
                schedules.history(job_id)[0].status in ("succeeded","failed","cancelled"),timeout=40))
        finally:
            scheduler.stop()

        record = schedules.history(job_id)[0]
        self.assertEqual(record.status,"succeeded",record.error_type)
        self.assertIsNotNone(record.finished_utc)
        self.assertEqual(schedules.list()[0].last_status,"succeeded")
        # Extracted text must not be written to SQLite.
        import sqlite3
        from contextlib import closing
        # sqlite3.Connection.__exit__ commits but does not close its Windows
        # file handle. Explicit closing is required before tempdir teardown.
        with closing(sqlite3.connect(self.store.db)) as conn:
            raw = str(conn.execute("SELECT * FROM schedule_runs").fetchall())
        self.assertNotIn("Autumn test",raw)
        self.assertTrue(eventually(lambda:not self.manager.active(profile.id),timeout=20))

    def test_user_closes_last_page_and_recorder_redacts_text(self):
        profile=self.store.save(Profile(name="recorder",browser="chromium",start_url=self.origin))
        self.manager.start(profile.id)
        self.assertTrue(eventually(lambda:(x:=self.manager._sessions.get(profile.id)) is not None and x.ready.is_set()))
        self.manager.start_recording(profile.id)
        # A real browser click and sensitive input event.
        async def perform():
            session=self.manager._sessions[profile.id]
            page=session.context.pages[0]
            await page.locator("#press").click()
            await page.locator("#secret").fill("do-not-record-password")
            await page.locator("#secret").dispatch_event("change")
            await page.locator("#category").select_option("sensitive-unique-option")
        self.manager._submit(perform()).result(timeout=20)
        self.assertTrue(eventually(lambda:len(self.manager.recorded_steps(profile.id))>=2))
        self.assertNotIn("do-not-record-password",str(self.manager.recorded_steps(profile.id)))
        self.assertNotIn("sensitive-unique-option",str(self.manager.recorded_steps(profile.id)))
        self.assertTrue(any(s.get("value")=="REVIEW_OPTION" for s in self.manager.recorded_steps(profile.id)))
        self.manager.stop_recording(profile.id)
        # Mimic the user closing the last window: do not call manager.stop().
        async def user_close():
            await self.manager._sessions[profile.id].context.pages[0].close()
        self.manager._submit(user_close()).result(timeout=20)
        self.assertTrue(eventually(lambda:not self.manager.active(profile.id)),"Closing last browser window must release OS lease")
        self.assertIsNone(self.manager.last_run(profile.id))
        self.manager.start(profile.id)
        self.assertTrue(eventually(lambda:(x:=self.manager._sessions.get(profile.id)) is not None and x.ready.is_set()))
        self.manager.stop(profile.id)

    def test_branded_chrome_and_edge_smoke(self):
        if os.environ.get("AUTUMN_BRANDED_ENGINE") != "1":
            self.skipTest("requires installed Google Chrome and Microsoft Edge")
        for engine in ("chrome", "msedge"):
            with self.subTest(engine=engine):
                profile=self.store.save(Profile(name=engine,browser=engine,start_url=self.origin))
                self.manager.start(profile.id)
                self.assertTrue(eventually(lambda:((x:=self.manager._sessions.get(profile.id)) is not None and x.ready.is_set())
                                    or not self.manager.active(profile.id),timeout=35),
                                f"{engine} did not resolve startup")
                self.assertTrue(self.manager.active(profile.id),f"{engine} browser closed unexpectedly")
                self.manager.stop(profile.id)
                self.assertTrue(eventually(lambda:not self.manager.active(profile.id),timeout=25))

    def test_multiengine_launch_smoke(self):
        if os.environ.get("AUTUMN_MULTI_ENGINE")!="1":self.skipTest("requires Firefox and WebKit binaries")
        for engine in ("firefox","webkit"):
            with self.subTest(engine=engine):
                profile=self.store.save(Profile(name=engine,browser=engine,start_url=self.origin))
                self.manager.start(profile.id)
                self.assertTrue(eventually(lambda:((x:=self.manager._sessions.get(profile.id)) is not None and x.ready.is_set())
                                    or not self.manager.active(profile.id)))
                self.assertTrue(self.manager.active(profile.id),f"{engine} browser failed to start")
                self.manager.stop(profile.id)
                self.assertTrue(eventually(lambda:not self.manager.active(profile.id)))

if __name__=="__main__":unittest.main()
