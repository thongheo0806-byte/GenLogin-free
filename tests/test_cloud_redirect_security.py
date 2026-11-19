"""Regression: an untrusted sync endpoint must not redirect bearer credentials.

Python urllib's standard HTTPRedirectHandler can forward Authorization from an
HTTPS or loopback API origin to another origin, including plaintext HTTP.
These tests use only synthetic loopback servers, not external networks.
"""
from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from autumn_genlogin.team_sync import CloudClient, HubError


class CloudRedirectSecurityTests(unittest.TestCase):
    def test_redirect_never_forwards_bearer_token(self):
        leaked = []

        class Sink(BaseHTTPRequestHandler):
            def do_GET(self):
                leaked.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *_args):
                pass

        sink = ThreadingHTTPServer(("127.0.0.1", 0), Sink)

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(self.server.redirect_status)
                self.send_header("Location", f"http://127.0.0.1:{sink.server_port}/token")
                self.end_headers()

            def log_message(self, *_args):
                pass

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        servers = (sink, redirect)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
        for thread in threads:
            thread.start()
        try:
            client = CloudClient(f"http://127.0.0.1:{redirect.server_port}")
            client.token = "synthetic-canary-not-a-real-token"
            for code in (301, 302, 303, 307, 308):
                with self.subTest(redirect_status=code):
                    redirect.redirect_status = code
                    with self.assertRaises(HubError) as refusal:
                        client.request("GET", "/teams/example/documents/profiles")
                    self.assertEqual(refusal.exception.status, 502)
                    self.assertEqual(leaked, [], "Bearer token reached redirect destination")
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
