"""Regressions from second external audit; real Chrome/Windows paths are tested in CI."""
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import uuid4

from autumn_genlogin.browser import BrowserManager
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store
from autumn_genlogin.services import save_profile_with_credentials, delete_profile_with_credentials


class DeletionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "app"
        self.store = Store(self.base)

    def _stage(self, pid):
        root = self.base / "delete-staging" / (f"{uuid4()}-{pid}")
        root.mkdir(parents=True)
        (root / "Cookies").write_text("private fixture session")
        return root

    def test_startup_retries_committed_deletion_cleanup(self):
        p = self.store.save(Profile())
        stage = self._stage(p.id)
        with self.store._connect() as c:
            c.execute("DELETE FROM profiles WHERE id=?", (p.id,))
        Store(self.base)  # simulate process restart after successful DB commit
        self.assertFalse(stage.exists(), "staged session must be erased after restart")

    def test_does_not_purge_data_before_db_delete_commit(self):
        p = self.store.save(Profile())
        stage = self._stage(p.id)  # simulate crash after rename but BEFORE DB commit
        Store(self.base)
        self.assertTrue(stage.exists(), "a still-present profile may need recovery")
        self.assertEqual(stage.joinpath("Cookies").read_text(), "private fixture session")

    def test_unknown_staging_names_are_not_deleted(self):
        stage = self.base / "delete-staging" / "manual-backup"
        stage.mkdir(parents=True)
        (stage / "Cookies").write_text("kept")
        report = Store(self.base).cleanup_staged_deletions()
        self.assertEqual(report["unsafe"], 1)
        self.assertTrue(stage.exists())

    def test_staging_cleanup_failure_retries_next_restart(self):
        p = self.store.save(Profile())
        stage = self._stage(p.id)
        with self.store._connect() as c:
            c.execute("DELETE FROM profiles WHERE id=?", (p.id,))
        with patch("autumn_genlogin.storage.shutil.rmtree", side_effect=PermissionError("locked")):
            self.assertEqual(self.store.cleanup_staged_deletions()["pending"], 1)
        self.assertTrue(stage.exists())
        self.assertEqual(Store(self.base).cleanup_staged_deletions()["pending"], 0)
        self.assertFalse(stage.exists())


class StartupAndValidationTests(unittest.TestCase):
    def test_upgrade_script_syncs_requirements_even_for_existing_venv(self):
        script = (Path(__file__).resolve().parents[1] / "START-WINDOWS.cmd").read_text()
        self.assertIn('".venv\\Scripts\\python.exe" -m pip install', script)
        self.assertLess(script.index('".venv\\Scripts\\python.exe" -m pip install'), script.index('".venv\\Scripts\\python.exe" main.py'))
        self.assertIn("main.py %*", script)

    def test_bad_database_does_not_crash_gui_without_dialog(self):
        from main import main
        with patch("tkinter.Tk") as create, patch("autumn_genlogin.ui.App", side_effect=sqlite3.DatabaseError("file is not a database")), patch("tkinter.messagebox.showerror") as popup, patch("sys.argv", ["main.py"]):
            create.return_value.tk.call.return_value = None
            self.assertEqual(main(), 1)
            self.assertTrue(popup.called)
            self.assertIn("--doctor", popup.call_args.args[1])
            create.return_value.destroy.assert_called_once()

    def test_proxy_host_checks_and_locale_case_insensitive(self):
        p = Profile(locale="vi-vn", proxy_scheme="http", proxy_host="::1", proxy_port=1080)
        p.validate()
        self.assertEqual(p.locale, "vi-VN")
        for host in ["-evil.com", "test..example", "256.256.256.256", "http://site", "example.com:80", "a" * 64 + ".com"]:
            with self.subTest(host=host), self.assertRaises(ValueError):
                Profile(proxy_scheme="http", proxy_host=host, proxy_port=8080).validate()
        for host in ["localhost", "example.com", "2001:db8::1", "127.0.0.1"]:
            with self.subTest(host=host):
                Profile(proxy_scheme="http", proxy_host=host, proxy_port=8080).validate()

    def test_switch_browser_with_attached_extension_rejected(self):
        import json
        from autumn_genlogin.extensions import ExtensionLibrary
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            store = Store(root / "app")
            profile = store.save(Profile(browser="chromium"))
            src = root / "extension"
            src.mkdir()
            (src / "manifest.json").write_text(json.dumps({"manifest_version": 3, "name": "Fixture", "version": "1"}))
            library = ExtensionLibrary(store)
            ext = library.install_folder(src)
            library.attach(profile.id, ext.id)
            profile.browser = "chrome"
            with self.assertRaisesRegex(ValueError, "Detach"):
                store.save(profile)
            self.assertEqual(store.get(profile.id).browser, "chromium")


class CredentialAndRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))

    def test_changing_username_without_password_retires_old_vault_entry(self):
        prev = self.store.save(Profile(proxy_scheme="http", proxy_host="localhost", proxy_port=8080, proxy_username="before"))
        updated = Profile(**prev.public_dict())
        updated.proxy_username = "after"
        deleted = []
        save_profile_with_credentials(self.store, updated, prev, "", set_secret=lambda *_: None, delete_secret=lambda pid: deleted.append(pid))
        self.assertEqual(deleted, [prev.id])

    def test_deleting_username_retires_vault_entry(self):
        prev = self.store.save(Profile(proxy_scheme="http", proxy_host="localhost", proxy_port=8080, proxy_username="before"))
        updated = Profile(**prev.public_dict())
        updated.proxy_username = ""
        deleted = []
        save_profile_with_credentials(self.store, updated, prev, "", set_secret=lambda *_: None, delete_secret=lambda pid: deleted.append(pid))
        self.assertEqual(deleted, [prev.id])

    def test_delete_service_revokes_run_and_vault_only_after_delete(self):
        p = self.store.save(Profile())
        calls = []
        leftovers, warning = delete_profile_with_credentials(self.store, p.id,
            delete_secret=lambda pid: calls.append(("vault", pid)),
            clear_run=lambda pid: calls.append(("run", pid)))
        self.assertEqual((leftovers, warning), ([], None))
        self.assertEqual(calls, [("run", p.id), ("vault", p.id)])
        self.assertEqual(self.store.all(), [])

    def test_credential_preserved_if_store_delete_fails(self):
        p = self.store.save(Profile())
        calls = []
        with patch.object(self.store, "delete", side_effect=OSError("locked")):
            with self.assertRaises(OSError):
                delete_profile_with_credentials(self.store, p.id, delete_secret=lambda *_: calls.append("vault"), clear_run=lambda *_: calls.append("run"))
        self.assertFalse(calls)

    def test_only_playwright_targetclosed_exception_is_closed(self):
        from playwright._impl._errors import TargetClosedError
        m = BrowserManager(self.store)
        self.assertFalse(m._is_target_closed(RuntimeError("failed selector on closed page target")))
        self.assertTrue(m._is_target_closed(TargetClosedError("Target closed")))

    def test_run_result_expires_and_can_be_cleared(self):
        m = BrowserManager(self.store)
        p = self.store.save(Profile())
        m._runs[p.id] = {"status":"succeeded", "extracted":[{"text":"secret"}]}
        m._run_timestamps[p.id] = time.monotonic() - m.RUN_RESULT_TTL_SECONDS - 1
        self.assertIsNone(m.last_run(p.id))
        self.assertNotIn(p.id, m._run_timestamps)
        m._runs[p.id] = {"extracted":[{"text":"new"}]}
        m._run_timestamps[p.id] = time.monotonic()
        m.clear_run(p.id)
        self.assertIsNone(m.last_run(p.id))


if __name__ == "__main__":
    unittest.main()
