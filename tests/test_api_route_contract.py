"""Golden local HTTP contract captured before the route-table refactor.

Use real authenticated loopback HTTP with synthetic deterministic services.
Existing integration tests independently cover actual storage and batch data.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

from autumn_genlogin.api import LocalAPI
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class RouteContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name))
        self.profile=self.store.save(Profile(name="Fixture",group_name="QA"))
        self.pid=self.profile.id
        self.bid="11111111-1111-4111-8111-111111111111"
        self.manager=Mock()
        self.manager.count.return_value=0
        self.manager.active.return_value=False
        self.manager.recorded_steps.return_value=[{"action":"click","selector":"#fixture"}]
        self.manager.last_run.return_value={"status":"succeeded","extracted":[]}
        self.schedules=Mock()
        self.schedules.list.return_value=[]
        self.schedules.history.return_value=[]
        self.batches=Mock()
        self.record={"id":self.bid,"status":"succeeded","items":[]}
        self.batches.list.return_value=[self.record]
        def batch_get(value):
            if str(UUID(value))!=self.bid:
                raise KeyError("unknown batch")
            return self.record
        def batch_cancel(value):
            if str(UUID(value))!=self.bid:
                raise KeyError("unknown batch")
        self.batches.get.side_effect=batch_get
        self.batches.cancel.side_effect=batch_cancel
        self.batches.start.return_value=self.bid
        self.api=LocalAPI(self.store,self.manager,self.schedules,self.batches)
        self.api.start(0)
        self.addCleanup(self.api.stop)
        self.base=f"http://127.0.0.1:{self.api.server.server_port}"

    def request(self,method,path,data=None,authorized=True):
        headers={"Content-Type":"application/json"}
        if authorized:
            headers["Authorization"]="Bearer "+self.api.token
        body=json.dumps(data).encode() if data is not None else None
        request=Request(self.base+path,method=method,data=body,headers=headers)
        try:
            response=urlopen(request,timeout=5)
        except HTTPError as exc:
            response=exc
        with response:
            self.assertEqual(response.headers["Cache-Control"],"no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"],"nosniff")
            return response.code,json.loads(response.read())

    def test_all_get_routes(self):
        root=f"/v1/profiles/{self.pid}"
        cases=(
            ("/v1/health",{"status":"ok","running":0}),
            ("/v1/profiles",{"profiles":[{"id":self.pid,"name":"Fixture",
                                            "group":"QA","running":False}]}),
            ("/v1/schedules",{"schedules":[]}),
            ("/v1/schedules/history?limit=3",{"runs":[]}),
            ("/v1/batches?limit=2",{"batches":[self.record]}),
            ("/v1/batches/"+self.bid,{"batch":self.record}),
            (root+"/recording",{"steps":self.manager.recorded_steps.return_value}),
            (root+"/runs/latest",{"run":self.manager.last_run.return_value}),
        )
        for path,expected in cases:
            with self.subTest(path=path):
                self.assertEqual(self.request("GET",path),(200,expected))
                self.assertEqual(self.request("GET",path,authorized=False),
                                 (401,{"error":"Unauthorized"}))
        self.schedules.history.assert_called_once_with(None,3)
        self.batches.list.assert_called_once_with(limit=2)

    def test_all_post_routes(self):
        root=f"/v1/profiles/{self.pid}"
        steps=[{"action":"wait","seconds":0}]
        graph={"format":"fixture"}
        actions={
            "open":("start",{},(self.pid,)),
            "stop":("stop",{},(self.pid,)),
            "run":("run_steps",{"steps":steps},(self.pid,steps)),
            "run-graph":("run_graph",{"graph":graph},(self.pid,graph)),
            "record-start":("start_recording",{},(self.pid,)),
            "record-stop":("stop_recording",{},(self.pid,)),
            "cancel":("cancel",{},(self.pid,)),
        }
        for action,(handler,data,args) in actions.items():
            with self.subTest(action=action):
                path=root+"/"+action
                self.assertEqual(self.request("POST",path,data,False),
                                 (401,{"error":"Unauthorized"}))
                self.assertEqual(self.request("POST",path,data),(202,{"accepted":True}))
                getattr(self.manager,handler).assert_called_once_with(*args)
        data={"profile_ids":[self.pid],"workflow":steps,"max_parallel":1}
        self.assertEqual(self.request("POST","/v1/batches",data),
                         (202,{"accepted":True,"batch_id":self.bid}))
        self.batches.start.assert_called_once_with([self.pid],steps,max_parallel=1)
        self.assertEqual(self.request("POST",f"/v1/batches/{self.bid}/cancel",{}),
                         (202,{"accepted":True}))
        self.batches.cancel.assert_called_once_with(self.bid)

    def test_error_and_path_compatibility(self):
        root=f"/v1/profiles/{self.pid}"
        missing="/v1/profiles/00000000-0000-0000-0000-000000000000"
        cases=(
            ("GET","/not-found",None,404,"Not found"),
            ("GET",root+"/recording/",None,404,"Not found"),
            ("GET",missing+"/recording",None,404,"Profile not found"),
            ("GET","/v1/profiles/not-uuid/recording",None,400,"Invalid profile ID"),
            ("GET","/v1/batches/not-uuid",None,400,"Invalid request parameters"),
            ("GET","/v1/batches/00000000-0000-0000-0000-000000000000",None,404,"Batch not found"),
            ("GET","/v1/batches?limit=bad",None,400,"Invalid request parameters"),
            ("POST",root+"/unknown",{},404,"Not found"),
            ("POST",missing+"/open",{},404,"Requested resource not found"),
            ("POST",root+"/run",{},400,"Missing required field: steps"),
            ("POST",root+"/run-graph",{},400,"Missing required field: graph"),
            ("POST","/v1/batches/00000000-0000-0000-0000-000000000000/cancel",{},404,
             "Batch is not active in this application"),
        )
        for method,path,data,status,error in cases:
            with self.subTest(method=method,path=path):
                self.assertEqual(self.request(method,path,data),(status,{"error":error}))
        self.assertEqual(self.request("GET","/v1/batches/"+self.bid+"/"),
                         (200,{"batch":self.record}))
        self.assertEqual(self.request("POST",root+"/open/",{}),(202,{"accepted":True}))
        self.manager.last_run.return_value=None
        self.assertEqual(self.request("GET",root+"/runs/latest"),
                         (404,{"error":"No recent workflow run"}))
        self.manager.start.side_effect=RuntimeError("private fixture")
        self.assertEqual(self.request("POST",root+"/open",{}),
                         (409,{"error":"Resource busy or action cannot be started"}))
        with patch.object(self.store,"all",side_effect=sqlite3.OperationalError("private fixture")):
            self.assertEqual(self.request("GET","/v1/profiles"),
                             (503,{"error":"Local storage unavailable; run Diagnostics"}))

    def test_disabled_optional_services_return_404(self):
        self.api.schedules=None
        self.api.batches=None
        for path in ("/v1/schedules","/v1/schedules/history","/v1/batches",
                     "/v1/batches/"+self.bid):
            self.assertEqual(self.request("GET",path),(404,{"error":"Not found"}))
        self.assertEqual(self.request("POST","/v1/batches",{}),(404,{"error":"Not found"}))


if __name__=="__main__":
    unittest.main()
