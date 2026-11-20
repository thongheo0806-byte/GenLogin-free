"""Authenticated local API exposes scheduler run history without page contents."""
from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autumn_genlogin.api import LocalAPI
from autumn_genlogin.models import Profile
from autumn_genlogin.scheduler import ScheduleStore
from autumn_genlogin.storage import Store


class APIHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name))
        self.profile=self.store.save(Profile(name="History API"))
        self.schedules=ScheduleStore(self.store)
        class Manager:
            def count(self): return 0
            def active(self, pid): return False
        self.api=LocalAPI(self.store,Manager(),self.schedules)
        self.api.start(port=0)
        self.url=f"http://127.0.0.1:{self.api.server.server_port}"

    def tearDown(self):
        self.api.stop()
        self.tmp.cleanup()

    def get(self,path,authorized=True):
        headers={"Authorization":"Bearer "+self.api.token} if authorized else {}
        request=urllib.request.Request(self.url+path,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=5) as response:
                return response.status,json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code,json.loads(exc.read())

    def test_history_is_authenticated_and_empty_by_default(self):
        self.assertEqual(self.get("/v1/schedules/history",False)[0],401)
        self.assertEqual(self.get("/v1/schedules/history"),(200,{"runs":[]}))

    def test_history_outcome_and_bounds(self):
        job_id=self.schedules.add(self.profile.id,[{"action":"wait","seconds":0}],
                  datetime.now(timezone.utc)-timedelta(minutes=1))
        [job]=self.schedules.claim_due()
        self.schedules.record_dispatched(job_id,job.dispatch_id)
        self.schedules.record_completion(job.dispatch_id,"failed","RuntimeError: secret")
        code,data=self.get("/v1/schedules/history?limit=1")
        self.assertEqual(code,200)
        self.assertEqual(data["runs"][0]["id"],job.dispatch_id)
        self.assertEqual(data["runs"][0]["status"],"failed")
        self.assertEqual(data["runs"][0]["error_type"],"RuntimeError")
        self.assertNotIn("secret",json.dumps(data))
        self.assertEqual(self.get("/v1/schedules/history?limit=0")[0],400)
        self.assertEqual(self.get("/v1/schedules/history?limit=1000")[0],400)
        self.assertEqual(self.get("/v1/schedules/history?limit=invalid")[0],400)
        self.assertEqual(self.get("/v1/schedules/history?schedule_id=../escape")[0],400)
        self.assertEqual(self.get("/v1/schedules/history?schedule_id="+job_id)[1]["runs"][0]["id"],job.dispatch_id)


if __name__=="__main__":
    unittest.main()
