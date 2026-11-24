"""Incremental Tk tab extraction while preserving App callback contracts."""
import inspect
import unittest

from autumn_genlogin.schedule_tab import ScheduleTabMixin
from autumn_genlogin.batch_tab import BatchTabMixin
from autumn_genlogin.ui import App
from autumn_genlogin.cloud_tab import CloudTabMixin


class ExtractedScheduleTabTests(unittest.TestCase):
    def test_app_inherits_all_scheduler_handlers_without_duplicate_definitions(self):
        expected=(
            "_dispatch_scheduled_job", "_build_schedule_tab",
            "refresh_schedules", "schedule_workflow",
            "remove_schedule", "retry_schedule",
        )
        self.assertTrue(issubclass(App, ScheduleTabMixin))
        for name in expected:
            with self.subTest(handler=name):
                self.assertTrue(callable(getattr(App,name)))
                self.assertIn(name,ScheduleTabMixin.__dict__)
                self.assertNotIn(name,App.__dict__,
                                 "Scheduler callback must be owned by extracted tab")

    def test_batch_tab_uses_app_bridge_and_owns_its_callbacks(self):
        expected=("_build_batch_tab", "start_group_batch", "cancel_group_batch",
                  "refresh_batches", "show_batch_details")
        self.assertTrue(issubclass(App,BatchTabMixin))
        for name in expected:
            with self.subTest(handler=name):
                self.assertIn(name,BatchTabMixin.__dict__)
                self.assertNotIn(name,App.__dict__)
        source=inspect.getsource(BatchTabMixin)
        self.assertIn("self._run_ui_task",source)
        self.assertNotIn("self.store._connect",source)
        self.assertNotIn(".result(timeout=",source)
        self.assertNotIn("asyncio.create_task(",source)

    def test_schedule_methods_only_depend_on_explicit_app_bridge(self):
        # This is a static architectural contract, not a UI test. The hosted
        # Windows pywinauto job continues to instantiate actual Tk controls.
        source=inspect.getsource(ScheduleTabMixin)
        self.assertIn("self._run_ui_task",source)
        self.assertIn("self.schedule_store",source)
        self.assertNotIn("self.store._connect",source)
        self.assertNotIn(".result(timeout=",source)
        self.assertNotIn("asyncio.create_task(",source)

    def test_cloud_tab_owns_handlers_and_uses_worker_bridge(self):
        self.assertTrue(issubclass(App,CloudTabMixin))
        for name in ("_build_cloud_tab","_cloud_action","cloud_login",
                     "cloud_register","cloud_sync","cloud_upload_session",
                     "cloud_download_session","cloud_list_sessions",
                     "cloud_revoke_session","cloud_invite"):
            with self.subTest(handler=name):
                self.assertIn(name,CloudTabMixin.__dict__)
                self.assertNotIn(name,App.__dict__)
        source=inspect.getsource(CloudTabMixin)
        self.assertIn("self._run_ui_task",source)
        self.assertNotIn(".result(timeout=",source)
        self.assertNotIn("self.store._connect",source)


if __name__ == "__main__":
    unittest.main()
