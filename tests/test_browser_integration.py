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



if __name__ == "__main__":
    unittest.main()
