"""Incremental Tk tab extraction while preserving App callback contracts."""
import inspect
import unittest

from autumn_genlogin.schedule_tab import ScheduleTabMixin
from autumn_genlogin.ui import App


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

    def test_schedule_methods_only_depend_on_explicit_app_bridge(self):
        # This is a static architectural contract, not a UI test. The hosted
        # Windows pywinauto job continues to instantiate actual Tk controls.
        source=inspect.getsource(ScheduleTabMixin)
        self.assertIn("self._run_ui_task",source)
        self.assertIn("self.schedule_store",source)
        self.assertNotIn("self.store._connect",source)
        self.assertNotIn(".result(timeout=",source)
        self.assertNotIn("asyncio.create_task(",source)


if __name__ == "__main__":
    unittest.main()
