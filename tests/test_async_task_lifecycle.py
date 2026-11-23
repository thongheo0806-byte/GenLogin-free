"""Playwright fire-and-forget tasks are owned until completion/cancellation."""
from __future__ import annotations

import asyncio
import queue
import unittest

from autumn_genlogin.browser_shared import SharedBrowserManager


class BackgroundTaskOwnershipTests(unittest.TestCase):
    def manager(self):
        manager=object.__new__(SharedBrowserManager)
        manager._background_tasks=set()
        manager.events=queue.Queue()
        return manager

    def test_active_task_stays_strongly_referenced_until_done(self):
        async def scenario():
            manager=self.manager()
            started=asyncio.Event()
            finish=asyncio.Event()

            async def pending():
                started.set()
                await finish.wait()
                return "completed"
            task=manager._spawn_background(pending())
            await started.wait()
            self.assertIn(task,manager._background_tasks)
            finish.set()
            self.assertEqual(await task,"completed")
            await asyncio.sleep(0)
            self.assertNotIn(task,manager._background_tasks)
            self.assertTrue(manager.events.empty())
        asyncio.run(scenario())

    def test_task_cancellation_releases_reference_without_false_errors(self):
        async def scenario():
            manager=self.manager()
            started=asyncio.Event()
            async def pending():
                started.set()
                await asyncio.Event().wait()
            task=manager._spawn_background(pending())
            await started.wait()
            self.assertIn(task,manager._background_tasks)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
            self.assertEqual(manager._background_tasks,set())
            self.assertTrue(manager.events.empty())
        asyncio.run(scenario())

    def test_unhandled_background_error_is_type_only(self):
        async def scenario():
            manager=self.manager()
            async def bad():
                raise RuntimeError("SENSITIVE_PAGE_URL_OR_COOKIE")
            task=manager._spawn_background(bad())
            await asyncio.gather(task,return_exceptions=True)
            await asyncio.sleep(0)
            self.assertEqual(manager._background_tasks,set())
            _,category,message=manager.events.get_nowait()
            self.assertEqual(category,"error")
            self.assertIn("RuntimeError",message)
            self.assertNotIn("SENSITIVE",message)
        asyncio.run(scenario())


if __name__=="__main__":
    unittest.main()
