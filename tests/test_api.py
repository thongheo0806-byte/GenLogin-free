import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sqlite3
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from autumn_genlogin.api import LocalAPI
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class StubManager:
    def count(self):
        return 0
    def active(self, _):
        return False
    def start(self, _):
        pass
    def stop(self, _):
        pass
    def cancel(self, _):
        pass
    def run_steps(self, _, __):
        pass
    def last_run(self, _):
        return None


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))
        self.profile = self.store.save(Profile(name="Test"))
        self.api = LocalAPI(self.store, StubManager())
        self.api.start(0)
        self.addCleanup(self.api.stop)
        self.url = "http://127.0.0.1:" + str(self.api.server.server_address[1])

    def request(self, path, token=None, method="GET", data=None):
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.url + path, method=method, headers=headers, data=None if data is None else json.dumps(data).encode())
        return urlopen(request, timeout=2)

    def test_rejects_missing_token(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request("/v1/profiles")
        self.assertEqual(ctx.exception.code, 401)

    def test_can_list_without_exposing_secrets(self):
        result = json.loads(self.request("/v1/profiles", token=self.api.token).read())
        self.assertEqual(result["profiles"][0]["name"], "Test")
        self.assertNotIn("proxy_username", result["profiles"][0])

    def test_nonexistent_profile_returns_404(self):
        missing = "/v1/profiles/00000000-0000-0000-0000-000000000000/open"
        with self.assertRaises(HTTPError) as ctx:
            self.request(missing, token=self.api.token, method="POST", data={})
        self.assertEqual(ctx.exception.code, 404)

    def test_unicode_authorization_header_returns_401_not_disconnect(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request("/v1/health", token="é")
        self.assertEqual(ctx.exception.code, 401)

    def test_missing_workflow_steps_is_400_not_404(self):
        endpoint = f"/v1/profiles/{self.profile.id}/run"
        with self.assertRaises(HTTPError) as ctx:
            self.request(endpoint, token=self.api.token, method="POST", data={})
        self.assertEqual(ctx.exception.code, 400)

    def test_invalid_profile_id_is_400(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request("/v1/profiles/not-a-uuid/run", token=self.api.token, method="POST", data={"steps": []})
        self.assertEqual(ctx.exception.code, 400)

    def test_last_run_endpoint_is_authenticated(self):
        with self.assertRaises(HTTPError) as ctx:
            self.request(f"/v1/profiles/{self.profile.id}/runs/latest", token=self.api.token)
        self.assertEqual(ctx.exception.code, 404)

    def test_database_error_returns_http_503_on_list(self):
        with patch.object(self.store, "all", side_effect=sqlite3.DatabaseError("corrupt")):
            with self.assertRaises(HTTPError) as err:
                self.request("/v1/profiles", token=self.api.token)
            self.assertEqual(err.exception.code, 503)
            self.assertNotIn("corrupt", err.exception.read().decode())

    def test_database_error_returns_http_503_on_mutation(self):
        with patch.object(self.store, "get", side_effect=sqlite3.DatabaseError("corrupt")):
            with self.assertRaises(HTTPError) as err:
                self.request(f"/v1/profiles/{self.profile.id}/open", token=self.api.token, method="POST", data={})
            self.assertEqual(err.exception.code, 503)

    def test_requires_auth_for_mutations(self):
        path = "/v1/profiles/" + self.profile.id + "/open"
        with self.assertRaises(HTTPError) as ctx:
            self.request(path, method="POST", data={})
        self.assertEqual(ctx.exception.code, 401)
        self.assertEqual(self.request(path, token=self.api.token, method="POST", data={}).status, 202)


if __name__ == "__main__":
    unittest.main()
