"""Incremental Tk tab extraction while preserving App callback contracts."""
import inspect
import unittest

from autumn_genlogin.schedule_tab import ScheduleTabMixin
from autumn_genlogin.batch_tab import BatchTabMixin
from autumn_genlogin.ui import App, ProfileEditor
from autumn_genlogin.profiles_tab import ProfilesTabMixin, ProfileEditor as OwnedProfileEditor
from autumn_genlogin.backup_tab import BackupTabMixin
from autumn_genlogin.extension_tab import ExtensionTabMixin
from autumn_genlogin.qa_sync_tab import QASyncTabMixin
from autumn_genlogin.miniapp_tab import MiniappTabMixin
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

    def test_qa_and_miniapp_controllers_own_their_callbacks(self):
        for mixin, handlers in (
            (QASyncTabMixin, ("_build_qa_sync_tab", "start_qa_sync",
                              "stop_qa_sync", "refresh_qa_sync")),
            (MiniappTabMixin, ("_build_miniapp_tab", "import_miniapp",
                "preview_miniapp", "load_miniapp", "remove_miniapp",
                "refresh_miniapps", "trust_miniapp_publisher")),
        ):
            self.assertTrue(issubclass(App,mixin))
            for handler in handlers:
                self.assertIn(handler,mixin.__dict__)
                self.assertNotIn(handler,App.__dict__)
            source=inspect.getsource(mixin)
            self.assertNotIn(".result(timeout=",source)
            self.assertNotIn("self.store._connect",source)
            self.assertNotIn("self.builder",source)
            self.assertNotIn("self.flow_tabs",source)
        self.assertIn("self.load_workflow_draft",
                      inspect.getsource(MiniappTabMixin))


    def test_backup_and_extension_controllers_own_their_callbacks(self):
        for mixin, handlers in (
            (BackupTabMixin, ("backup_profile", "restore_profile",
                              "export_profiles", "import_profiles")),
            (ExtensionTabMixin, ("_build_extensions_tab", "refresh_extensions",
                "install_extension_folder", "install_extension_zip",
                "update_extension_zip", "rollback_extension_update",
                "attach_extension", "detach_extension", "remove_extension")),
        ):
            self.assertTrue(issubclass(App,mixin))
            for handler in handlers:
                self.assertIn(handler,mixin.__dict__)
                self.assertNotIn(handler,App.__dict__)
            source=inspect.getsource(mixin)
            self.assertNotIn(".result(timeout=",source)
            self.assertNotIn("self.store._connect",source)
            self.assertNotIn("self.builder",source)
            self.assertNotIn("self.flow_tabs",source)
            self.assertNotIn("self.tree",source)
        self.assertIn("self._run_ui_task",inspect.getsource(BackupTabMixin))


    def test_profiles_controller_and_app_shell_size(self):
        self.assertTrue(issubclass(App,ProfilesTabMixin))
        self.assertIs(ProfileEditor,OwnedProfileEditor)
        for handler in ("_build_profiles_tab","selected_id","refresh",
                        "render_cached_profiles","new_profile","edit_profile",
                        "clone_profile","open_profile","open_group",
                        "delete_profile","update_profile_status",
                        "profile_group_snapshot","cancel_profile_search"):
            self.assertIn(handler,ProfilesTabMixin.__dict__)
            self.assertNotIn(handler,App.__dict__)
        source=inspect.getsource(App)
        self.assertNotIn("self.tree",source)
        self.assertNotIn("self._cached_profiles",source)
        batch=inspect.getsource(BatchTabMixin)
        self.assertIn("self.profile_group_snapshot",batch)
        self.assertNotIn("self.group.",batch)
        self.assertNotIn("self._cached_profiles",batch)
        cloud=inspect.getsource(CloudTabMixin)
        self.assertNotIn("self.builder",cloud)
        self.assertNotIn("self.flow_tabs",cloud)
        self.assertNotIn("self.graph_builder",cloud)
        from pathlib import Path
        self.assertLess(len(Path(inspect.getfile(App)).read_text(encoding="utf-8").splitlines()),600)



if __name__ == "__main__":
    unittest.main()
