"""Driver terminal shutdown behavior without requiring browser binaries."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autumn_genlogin.browser_shared import SharedBrowserManager
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class DriverShutdownTests(unittest.TestCase):
    def test_cold_close_is_idempotent_and_rejects_late_profile_open(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root))
            profile=store.save(Profile(name="Synthetic shutdown profile"))
            manager=SharedBrowserManager(store,headless=True)
            manager.close_driver()
            manager.close_driver()
            with self.assertRaisesRegex(RuntimeError,"shutting down"):
                manager.start(profile.id)
            self.assertEqual(manager.count(),0)
            self.assertIsNone(manager._thread)

    def test_profile_close_requires_sessions_to_stop_first(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root))
            profile=store.save(Profile(name="Synthetic open state"))
            manager=SharedBrowserManager(store,headless=True)
            from autumn_genlogin.browser_shared import Session
            with manager._lock:
                manager._sessions[profile.id]=Session(profile)
            with self.assertRaisesRegex(RuntimeError,"Close profiles"):
                manager.close_driver()
            self.assertFalse(manager._shutdown_requested)
            with manager._lock:
                manager._sessions.clear()
            manager.close_driver()


if __name__=="__main__":
    unittest.main()
