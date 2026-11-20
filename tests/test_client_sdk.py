"""End-to-end local HTTP client SDK validation without public network calls."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

from autumn_genlogin.api import LocalAPI
from autumn_genlogin.batch import BatchRunner
from autumn_genlogin.client import AutumnAPIClient, LocalAPIError
from autumn_genlogin.graph import steps_to_graph
from autumn_genlogin.models import Profile
from autumn_genlogin.scheduler import ScheduleStore
from autumn_genlogin.storage import Store


class StubManager:
    MAX_BROWSERS=6
    def __init__(self):
        self.started=[]
        self.stopped=[]
        self.runs=[]
        self.reject=False
    def count(self):return 0
    def active(self,pid):return False
    def start(self,pid):
        if self.reject:raise RuntimeError("internal private account value")
        self.started.append(pid)
    def stop(self,pid):self.stopped.append(pid)
    def run_steps(self,pid,steps):self.runs.append((pid,steps))
    def run_graph(self,pid,graph):self.runs.append((pid,graph))
    def cancel(self,pid):pass
    def last_run(self,pid):return {"id":str(uuid4()),"status":"succeeded","extracted":[]}
    def start_recording(self,pid):pass
    def stop_recording(self,pid):pass
    def recorded_steps(self,pid):return [{"action":"wait","seconds":0}]
    def start_workflow(self,pid,workflow,*,on_finish,run_id=None):
        self.runs.append((pid,workflow))
        on_finish("succeeded",None)
        return str(uuid4())


def eventually(predicate, timeout=3):
    stop=time.monotonic()+timeout
    while time.monotonic()<stop:
        if predicate():return True
        time.sleep(0.02)
    return False


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name))
        self.profile=self.store.save(Profile(name="Client Test"))
        self.manager=StubManager()
        self.schedules=ScheduleStore(self.store)
        self.batches=BatchRunner(self.store,self.manager)
        self.api=LocalAPI(self.store,self.manager,self.schedules,self.batches)
        self.api.start(port=0)
        self.client=AutumnAPIClient(self.api.token,
                     url=f"http://127.0.0.1:{self.api.server.server_port}")

    def tearDown(self):
        self.api.stop()
        self.temp.cleanup()

    def test_get_profile_and_health_then_actions(self):
        self.assertEqual(self.client.health()["status"],"ok")
        self.assertEqual(self.client.profiles()[0]["id"],self.profile.id)
        self.assertTrue(self.client.open_profile(self.profile.id)["accepted"])
        self.assertEqual(self.manager.started,[self.profile.id])
        steps=[{"action":"wait","seconds":0}]
        self.assertTrue(self.client.run_steps(self.profile.id,steps)["accepted"])
        self.assertEqual(self.manager.runs[-1],(self.profile.id,steps))
        graph=steps_to_graph(steps)
        self.assertTrue(self.client.run_graph(self.profile.id,graph)["accepted"])
        self.assertEqual(self.manager.runs[-1][1],graph)
        self.assertEqual(self.client.latest_run(self.profile.id)["status"],"succeeded")
        self.assertEqual(self.client.recorded_steps(self.profile.id)[0]["action"],"wait")
        self.client.start_recording(self.profile.id)
        self.client.stop_recording(self.profile.id)
        self.client.cancel_run(self.profile.id)
        self.client.stop_profile(self.profile.id)
        self.assertEqual(self.manager.stopped,[self.profile.id])

    def test_authenticated_batch_and_schedule_endpoints(self):
        self.assertEqual(self.client.schedules(),[])
        self.assertEqual(self.client.schedule_history(),[])
        key=self.client.start_batch([self.profile.id],[{"action":"wait","seconds":0}])
        self.assertTrue(eventually(lambda:self.client.batch(key)["status"]=="succeeded"))
        self.assertEqual(self.client.batch(key)["items"][0]["status"],"succeeded")
        self.assertEqual(self.client.batches()[0]["id"],key)
        self.assertTrue(self.client.cancel_batch(key)["accepted"])

    def test_bad_token_and_unavailable_api_use_typed_error(self):
        bad=AutumnAPIClient("incorrect_bearer_token_value",
              url=self.client.url)
        with self.assertRaises(LocalAPIError) as ctx:
            bad.health()
        self.assertEqual(ctx.exception.status,401)
        with self.assertRaises(LocalAPIError) as ctx:
            self.client.open_profile(str(uuid4()))
        self.assertEqual(ctx.exception.status,404)

    def test_busy_browser_maps_to_safe_409_not_connection_reset(self):
        self.manager.reject=True
        with self.assertRaises(LocalAPIError) as ctx:
            self.client.open_profile(self.profile.id)
        self.assertEqual(ctx.exception.status,409)
        self.assertNotIn("private account value",str(ctx.exception))

    def test_sensitive_tokens_hidden_and_inputs_validated_before_network(self):
        self.assertNotIn(self.api.token,repr(self.client))
        with self.assertRaises(ValueError):
            self.client.open_profile("../escape")
        with self.assertRaises(ValueError):
            self.client.run_steps(self.profile.id,[{"action":"eval","code":"print(1)"}])
        with self.assertRaises(ValueError):
            self.client.start_batch([self.profile.id]*2,[{"action":"wait","seconds":0}])
        with self.assertRaises(ValueError):
            self.client.batch("not-uuid")
        with self.assertRaises(ValueError):
            self.client.schedule_history(limit=201)
        with self.assertRaises(ValueError):
            self.client.batches(limit=100)
        self.assertEqual(self.manager.runs,[])

    def test_refuses_external_insecure_and_ambiguous_urls(self):
        for url in ("http://example.com:8765",
                    "https://127.0.0.1:8765",
                    "http://127.0.0.1:8765/something",
                    "http://user:pass@127.0.0.1:8765",
                    "http://127.0.0.1",
                    "http://127.0.0.1:8765/?token=secret"):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    AutumnAPIClient(self.api.token,url=url)


class SDKRedirectTests(unittest.TestCase):
    def test_redirect_never_forwards_bearer_even_to_another_loopback_port(self):
        leaked=[]
        class Receiver(BaseHTTPRequestHandler):
            def do_GET(self):
                leaked.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            def log_message(self,*args):pass

        receiver=ThreadingHTTPServer(("127.0.0.1",0),Receiver)
        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location",f"http://127.0.0.1:{receiver.server_port}/v1/health")
                self.end_headers()
            def log_message(self,*args):pass
        redirect=ThreadingHTTPServer(("127.0.0.1",0),Redirect)
        servers=[receiver,redirect]
        threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
        for th in threads:th.start()
        try:
            canary="synthetic_secret_token_12345"
            client=AutumnAPIClient(canary,url=f"http://127.0.0.1:{redirect.server_port}")
            with self.assertRaises(LocalAPIError) as ctx:
                client.health()
            self.assertEqual(ctx.exception.status,502)
            self.assertEqual(leaked,[])
        finally:
            for s in servers:s.shutdown();s.server_close()
            for th in threads:th.join(timeout=4)


if __name__=="__main__":
    unittest.main()
