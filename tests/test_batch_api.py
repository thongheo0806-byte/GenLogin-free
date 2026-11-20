"""Authenticated local batch API: positive path and rejection tests."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from autumn_genlogin.api import LocalAPI
from autumn_genlogin.batch import BatchRunner
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class APIManager:
    MAX_BROWSERS=6
    def __init__(self):
        self.calls=[]
    def count(self): return 0
    def active(self,pid): return False
    def start_workflow(self,pid,flow,*,on_finish=None,run_id=None):
        self.calls.append(pid)
        if on_finish:on_finish("succeeded",None)
        return "fake-run-id"
    def last_run(self,pid): return None
    def cancel(self,pid): pass


class APIBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name))
        self.profile=self.store.save(Profile(name="API batch"))
        self.manager=APIManager()
        self.batch=BatchRunner(self.store,self.manager)
        self.api=LocalAPI(self.store,self.manager,batches=self.batch)
        self.api.start(port=0)
        self.base=f"http://127.0.0.1:{self.api.server.server_port}"

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def request(self,path,body=None,auth=True):
        headers={"Content-Type":"application/json"}
        if auth:headers["Authorization"]="Bearer "+self.api.token
        encoded=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(self.base+path,data=encoded,headers=headers,
                                   method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req,timeout=5) as resp:
                return resp.status,json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code,json.loads(exc.read())

    def test_batch_endpoints_require_token_and_validate_inputs(self):
        self.assertEqual(self.request("/v1/batches",auth=False)[0],401)
        self.assertEqual(self.request("/v1/batches",{"profile_ids":[self.profile.id],
                         "workflow":[{"action":"wait","seconds":0}]},auth=False)[0],401)
        code,data=self.request("/v1/batches",{"profile_ids":[self.profile.id],
                    "workflow":[{"action":"wait","seconds":0}],"max_parallel":1})
        self.assertEqual(code,202)
        key=data["batch_id"]
        self.assertEqual(self.request("/v1/batches/"+key)[0],200)
        self.assertEqual(self.request("/v1/batches")[0],200)
        self.assertEqual(self.request("/v1/batches?limit=100")[0],400)
        self.assertEqual(self.request("/v1/batches/invalid")[0],400)
        self.assertEqual(self.request("/v1/batches",{"profile_ids":[],"workflow":[]})[0],400)


if __name__=="__main__":
    unittest.main()
