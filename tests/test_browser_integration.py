"""Real Chromium tests against loopback-only fixture.

Set AUTUMN_E2E=1 after `python -m playwright install chromium`.
No third-party sites, accounts, proxies or platform anti-abuse checks are used.
"""
import os
import time
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        content = b"<html><body><h1>Local fixture</h1><input id='name'><button id='save'>Save</button></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, *_):
        pass


@unittest.skipUnless(os.environ.get("AUTUMN_E2E") == "1", "requires installed Chromium and AUTUMN_E2E=1")
class BrowserIntegrationTests(unittest.TestCase):
    def test_real_chromium_isolation_navigation_and_profile_persistence(self):
        from playwright.sync_api import sync_playwright
        from autumn_genlogin.models import Profile
        from autumn_genlogin.storage import Store
        with tempfile.TemporaryDirectory() as base:
            store = Store(Path(base))
            alpha = store.save(Profile(name="alpha", browser="chromium"))
            beta = store.save(Profile(name="beta", browser="chromium"))
            server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            origin = f"http://127.0.0.1:{server.server_address[1]}"
            with sync_playwright() as pw:
                # Real browser binary, not a mocked Playwright class.
                c1 = pw.chromium.launch_persistent_context(str(store.profile_path(alpha.id)), headless=True)
                try:
                    page = c1.new_page()
                    page.goto(origin)
                    self.assertEqual(page.locator("h1").inner_text(), "Local fixture")
                    page.evaluate("localStorage.setItem('owner','alpha')")
                    page.context.add_cookies([{"name": "label", "value": "alpha", "url": origin, "expires": time.time() + 3600}])
                finally:
                    c1.close()
                c2 = pw.chromium.launch_persistent_context(str(store.profile_path(beta.id)), headless=True)
                try:
                    page = c2.new_page()
                    page.goto(origin)
                    self.assertIsNone(page.evaluate("localStorage.getItem('owner')"))
                    self.assertEqual([c for c in c2.cookies() if c["name"] == "label"], [])
                finally:
                    c2.close()
                c3 = pw.chromium.launch_persistent_context(str(store.profile_path(alpha.id)), headless=True)
                try:
                    page = c3.new_page()
                    page.goto(origin)
                    self.assertEqual(page.evaluate("localStorage.getItem('owner')"), "alpha")
                    self.assertEqual([c["value"] for c in c3.cookies() if c["name"] == "label"], ["alpha"])
                finally:
                    c3.close()



    def test_real_shared_manager_workflow_and_lifecycle(self):
        """Exercise production shared manager's linear workflow and lifecycle."""
        from autumn_genlogin.browser_shared import SharedBrowserManager
        from autumn_genlogin.models import Profile
        from autumn_genlogin.storage import Store
        with tempfile.TemporaryDirectory() as base:
            store=Store(Path(base))
            server=ThreadingHTTPServer(("127.0.0.1",0), Fixture)
            thread=threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                origin=f"http://127.0.0.1:{server.server_address[1]}"
                profile=store.save(Profile(name="SharedBrowserManager fixture", browser="chromium", start_url=origin))
                manager=SharedBrowserManager(store, headless=True)
                manager.start(profile.id)
                def await_condition(condition, seconds=20):
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        if condition(): return True
                        time.sleep(.05)
                    return False
                try:
                    self.assertTrue(await_condition(lambda: any(item[1]=="status" and item[2]=="Running" for item in list(manager.events.queue))),
                                    f"Browser failed to open: {list(manager.events.queue)}")
                    manager.run_steps(profile.id,[{"action":"wait_for","selector":"h1"},
                                                   {"action":"extract_text","selector":"h1"}])
                    self.assertTrue(await_condition(lambda: (manager.last_run(profile.id) or {}).get("status") in {"succeeded","failed","cancelled"}),
                                    f"Workflow never completed: {manager.last_run(profile.id)}")
                    run=manager.last_run(profile.id)
                    self.assertEqual(run["status"],"succeeded",run)
                    self.assertEqual(run["extracted"][0]["text"],"Local fixture")
                finally:
                    manager.stop_all()
                    self.assertTrue(await_condition(lambda: manager.count()==0),"SharedBrowserManager session/lease not released")
                    manager.close_driver()
            finally:
                server.shutdown()
                server.server_close()

    @unittest.skipUnless(os.name == "nt", "Windows process lifetime integration")
    def test_browser_process_exit_releases_profile_manager_and_secret_results(self):
        """Terminate ONLY our own Chromium process to simulate abrupt browser exit.

        This is a forced-exit check, not a claim that user-initiated window close
        behaves identically under every window manager.
        """
        import psutil
        from autumn_genlogin.browser_shared import SharedBrowserManager
        from autumn_genlogin.models import Profile
        from autumn_genlogin.storage import Store
        with tempfile.TemporaryDirectory() as base:
            store = Store(Path(base) / "app")
            profile = store.save(Profile(name="forced-close", browser="chromium", start_url="http://127.0.0.1:1"))
            manager = SharedBrowserManager(store, headless=True)
            manager.start(profile.id)
            try:
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if any(evt[1] == "status" and evt[2] == "Running" for evt in list(manager.events.queue)):
                        break
                    time.sleep(.1)
                else:
                    self.fail(f"Browser did not start: {list(manager.events.queue)}")
                manager._runs[profile.id] = {"status":"succeeded", "extracted":[{"text":"fixture secret"}]}
                manager._run_timestamps[profile.id] = time.monotonic()
                # Only kill a process commandline referencing this exact
                # temporary profile user-data-dir, never an unrelated browser.
                owned_dir = str(store.profile_path(profile.id)).lower()
                matches = []
                for process in psutil.process_iter(["pid", "name", "cmdline"]):
                    try:
                        cmdline = process.info["cmdline"] or []
                        name = (process.info["name"] or "").lower()
                        if ("chrome" in name or "chromium" in name or "headless" in name) and any(
                            owned_dir in arg.lower() and "--user-data-dir" in arg.lower() for arg in cmdline
                        ):
                            matches.append(process)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                self.assertTrue(matches, "Could not locate the owned Chromium main process")
                for process in matches:
                    try:
                        process.kill()
                    except psutil.NoSuchProcess:
                        pass
                deadline = time.monotonic() + 20
                while manager.active(profile.id) and time.monotonic() < deadline:
                    time.sleep(.1)
                self.assertFalse(manager.active(profile.id), "worker lease not released after browser process exit")
                self.assertIsNone(manager.last_run(profile.id), "extracted text must not survive browser exit")
            finally:
                manager.stop_all()
                deadline = time.monotonic() + 25
                while manager.count() and time.monotonic() < deadline:
                    time.sleep(.1)
                self.assertEqual(manager.count(), 0)
                manager.close_driver()

    def test_real_chromium_loads_opt_in_mv3_extension(self):
        import json
        from playwright.sync_api import sync_playwright
        from autumn_genlogin.extensions import ExtensionLibrary
        from autumn_genlogin.models import Profile
        from autumn_genlogin.storage import Store
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            store = Store(root / "app")
            profile = store.save(Profile(name="extension fixture", browser="chromium"))
            source = root / "extension"
            source.mkdir()
            (source / "manifest.json").write_text(json.dumps({
                "manifest_version": 3, "name": "Local fixture extension", "version": "0.1.0",
                "background": {"service_worker": "worker.js"}
            }))
            (source / "worker.js").write_text("chrome.runtime.onInstalled.addListener(() => {});")
            library = ExtensionLibrary(store)
            extension = library.install_folder(source)
            library.attach(profile.id, extension.id)
            [extension_path] = library.paths_for(profile.id)
            with sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(store.profile_path(profile.id)), channel="chromium", headless=True,
                    args=[f"--disable-extensions-except={extension_path}", f"--load-extension={extension_path}"])
                try:
                    workers = context.service_workers
                    worker = workers[0] if workers else context.wait_for_event("serviceworker", timeout=15000)
                    self.assertTrue(worker.url.startswith("chrome-extension://"))
                finally:
                    context.close()


if __name__ == "__main__":
    unittest.main()
