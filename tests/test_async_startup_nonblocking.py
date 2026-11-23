"""Regression: slow keyring/extension I/O must not stall shared Playwright loop."""
from __future__ import annotations

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from autumn_genlogin.browser_shared import Session, SharedBrowserManager
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class FakePage:
    def on(self, *_args):
        pass

    async def goto(self, *_args, **_kwargs):
        pass


class FakeContext:
    def __init__(self):
        self.pages = [FakePage()]
        self.closed = False

    def on(self, *_args):
        pass

    async def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, context):
        self.context = context

    async def launch_persistent_context(self, **_kwargs):
        return self.context


class SlowStartupIOTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name), reuse_connections=True)
        self.context = FakeContext()
        self.manager = SharedBrowserManager(self.store, headless=True)
        self.manager._playwright = SimpleNamespace(chromium=FakeBrowser(self.context))

    def tearDown(self):
        self.store.close_thread_connection()
        self.temp.cleanup()

    def assert_loop_stays_responsive(self, profile):
        """A timer must run while startup spends 0.6s inside slow I/O."""
        async def exercise():
            session = Session(profile)
            loop = asyncio.get_running_loop()
            started = loop.time()
            observed = []
            loop.call_later(0.04, lambda: observed.append(loop.time() - started))
            opening = asyncio.create_task(self.manager._open(session))
            try:
                await asyncio.wait_for(session.ready.wait(), timeout=5)
            finally:
                session.closed.set()
                await asyncio.wait_for(opening, timeout=5)
            self.assertTrue(observed, "Event loop timer never fired")
            self.assertLess(observed[0], 0.4,
                            "Slow synchronous I/O stalled unrelated browser tasks")
            self.assertTrue(self.context.closed)
        asyncio.run(exercise())

    def test_slow_windows_keyring_lookup_does_not_block_other_tasks(self):
        profile = self.store.save(Profile(
            name="Synthetic keyring fixture", browser="chromium",
            proxy_scheme="http", proxy_host="proxy.example",
            proxy_port=8080, proxy_username="fixture",
        ))
        def slow_password(_pid):
            time.sleep(0.6)
            return "synthetic-only"
        with patch("autumn_genlogin.browser_shared.get_password",
                   side_effect=slow_password):
            self.assert_loop_stays_responsive(profile)

    def test_slow_extension_catalog_read_does_not_block_other_tasks(self):
        profile = self.store.save(Profile(
            name="Synthetic extension fixture", browser="chromium",
        ))
        def slow_paths(_pid):
            time.sleep(0.6)
            return []
        with patch.object(self.manager.extensions, "paths_for",
                          side_effect=slow_paths):
            self.assert_loop_stays_responsive(profile)


if __name__ == "__main__":
    unittest.main()
