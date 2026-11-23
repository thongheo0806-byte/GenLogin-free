"""Synthetic slow-I/O heartbeat probes for the single shared Playwright loop."""
from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from autumn_genlogin.browser_shared import Session, SharedBrowserManager
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class AsyncCompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name),reuse_connections=True)
        self.profile=self.store.save(Profile(name="Synthetic async completion"))
        self.manager=SharedBrowserManager(self.store,headless=True)

    def tearDown(self):
        self.store.close_thread_connection()
        self.tmp.cleanup()

    def test_slow_journal_commit_does_not_block_other_browser_tasks(self):
        owner=threading.get_ident()
        worker_threads=[]
        observed=[]
        def slow_commit(status,error):
            worker_threads.append(threading.get_ident())
            time.sleep(0.6)
            self.assertEqual(status,"succeeded")
            self.assertIsNone(error)
        async def exercise():
            session=Session(self.profile)
            session.context=SimpleNamespace(pages=[object()])
            session.ready.set()
            pid=self.profile.id
            self.manager._runs[pid]={
                "id":"fixture","status":"queued","total_steps":1,
                "extracted":[],"error":None}
            started=asyncio.get_running_loop().time()
            asyncio.get_running_loop().call_later(
                0.04,lambda:observed.append(asyncio.get_running_loop().time()-started))
            await self.manager._perform(session,[{"action":"wait","seconds":0}],
                                        "steps",on_finish=slow_commit)
        asyncio.run(exercise())
        self.assertTrue(observed,"Async loop timer was starved")
        self.assertLess(observed[0],0.4)
        self.assertTrue(worker_threads)
        self.assertNotEqual(worker_threads[0],owner)

    def test_slow_image_catalog_read_does_not_block_loop(self):
        observed=[]
        clicks=[]
        class FakePage:
            async def screenshot(self,**_kwargs):
                return b"synthetic-screenshot"
            mouse=SimpleNamespace(click=lambda *_args: asyncio.sleep(0))
        async def exercise():
            session=Session(self.profile)
            session.context=SimpleNamespace(pages=[FakePage()])
            session.ready.set()
            started=asyncio.get_running_loop().time()
            asyncio.get_running_loop().call_later(
                0.04,lambda:observed.append(asyncio.get_running_loop().time()-started))
            with (patch.object(self.manager.image_templates,"read",
                               side_effect=lambda _id:(time.sleep(0.6),b"sample")[1]),
                  patch("autumn_genlogin.browser_shared.find_image_center",
                        return_value=(11,17))):
                await self.manager._action(session,{
                    "action":"click_image","template_id":"0"*64,
                    "confidence":0.93},1)
        asyncio.run(exercise())
        self.assertTrue(observed)
        self.assertLess(observed[0],0.4)


if __name__=="__main__":
    unittest.main()
