"""Regressions for user-provided 2026-11-19 audit of AutumnGenLogin.

Reproduction scripts from another environment were not accessible here; these
independently verify the reported call chains against the inspected GitHub SHA.
"""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from autumn_genlogin.browser_shared import Session, SharedBrowserManager
from autumn_genlogin.locks import ProfileLease
from autumn_genlogin.diagnostics import audit_store
from autumn_genlogin.extensions import ExtensionLibrary
from autumn_genlogin.models import Profile, validated_steps
from autumn_genlogin.storage import Store


class StoreRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.store = Store(self.base / "store")

    def test_doctor_does_not_initialize_corrupt_database(self):
        self.store.db.write_bytes(b"definitely not a SQLite database")
        p = subprocess.run([sys.executable, "main.py", "--doctor-json"],
                           env={**os.environ, "AUTUMN_GENLOGIN_HOME": str(self.store.base)},
                           cwd=Path(__file__).resolve().parents[1],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        self.assertEqual(p.returncode, 1, p.stderr)
        report = json.loads(p.stdout)
        self.assertEqual(next(c["status"] for c in report["checks"] if c["name"] == "database_integrity"), "fail")

    def test_doctor_does_not_create_missing_database(self):
        home = self.base / "missing#catalog?"
        p = subprocess.run([sys.executable, "main.py", "--doctor-json"],
                           env={**os.environ, "AUTUMN_GENLOGIN_HOME": str(home)},
                           cwd=Path(__file__).resolve().parents[1],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertFalse(home.exists(), "doctor should not initialize a missing local data directory")
        self.assertGreater(json.loads(p.stdout)["summary"]["failed"], 0)

    def test_uri_reserved_characters_do_not_alias_other_files(self):
        store = Store(self.base / ("a#b%c" if os.name == "nt" else "a#b?c%"))
        store.db.write_bytes(b"corrupt file")
        report = audit_store(store)
        result = next(c for c in report["checks"] if c["name"] == "database_integrity")
        self.assertEqual(result["status"], "fail")
        self.assertFalse((self.base / "a").exists(), "diagnostics must never create an unexpected DB")

    def test_failed_db_delete_restores_browser_data(self):
        p = self.store.save(Profile(name="Keep me"))
        directory = self.store.profile_path(p.id)
        directory.mkdir()
        (directory / "cookies").write_bytes(b"test data")
        original = self.store._connect
        counter = 0
        def fail_third():
            nonlocal counter
            counter += 1
            if counter == 3:
                raise sqlite3.OperationalError("simulated database error")
            return original()
        with patch.object(self.store, "_connect", side_effect=fail_third):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.delete(p.id)
        self.assertEqual(self.store.get(p.id).name, "Keep me")
        self.assertEqual((directory / "cookies").read_bytes(), b"test data")

    def test_failed_directory_move_does_not_delete_db(self):
        p = self.store.save(Profile(name="Keep me"))
        directory = self.store.profile_path(p.id)
        directory.mkdir()
        with patch("autumn_genlogin.storage.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.store.delete(p.id)
        self.assertIsNotNone(self.store.get(p.id))
        self.assertTrue(directory.exists())

    def test_import_is_one_transaction(self):
        payload = {"format": "AutumnGenLogin/1", "profiles": [Profile(name="first").public_dict(), Profile(name="second").public_dict()]}
        src = self.base / "import.json"
        src.write_text(json.dumps(payload), encoding="utf-8")
        original = self.store._save_with_connection
        counter = 0
        def flaky(conn, profile):
            nonlocal counter
            counter += 1
            if counter == 2:
                raise sqlite3.OperationalError("simulated disk failure")
            return original(conn, profile)
        with patch.object(self.store, "_save_with_connection", side_effect=flaky):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.import_metadata(src)
        self.assertEqual(self.store.all(), [])

    def test_invalid_import_name_type_is_validation_error(self):
        payload = Profile(name="good").public_dict()
        payload["name"] = 123
        source = self.base / "bad.json"
        source.write_text(json.dumps({"format":"AutumnGenLogin/1", "profiles":[payload]}))
        with self.assertRaises(ValueError):
            self.store.import_metadata(source)
        self.assertEqual(self.store.all(), [])

    def test_foreign_keys_and_schema_version(self):
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)


class ModelRegressions(unittest.TestCase):
    def test_rejects_invalid_timezone_and_locale(self):
        with self.assertRaises(ValueError):
            Profile(timezone_id="Foo/Bar").validate()
        with self.assertRaises(ValueError):
            Profile(locale="Foo/Bar").validate()

    def test_disallow_socks5_credentials(self):
        with self.assertRaises(ValueError):
            Profile(proxy_scheme="socks5", proxy_host="127.0.0.1", proxy_port=1080, proxy_username="user").validate()

    def test_can_clear_text_field(self):
        self.assertEqual(validated_steps([{"action":"fill", "selector":"#input", "text":""}])[0]["text"], "")

    def test_extension_uppercase_profile_id_matches(self):
        with tempfile.TemporaryDirectory() as home:
            store = Store(Path(home) / "app")
            lib = ExtensionLibrary(store)
            p = store.save(Profile(browser="chromium"))
            with tempfile.TemporaryDirectory() as source:
                d=Path(source); (d/"manifest.json").write_text(json.dumps({"manifest_version":3,"name":"test","version":"1"}))
                rec=lib.install_folder(d)
                lib.attach(p.id.upper(), rec.id.upper())
                self.assertEqual(lib.attached_ids(p.id), [rec.id])


class BrowserLifecycleRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name))

    def test_manually_closed_browser_releases_worker_without_stop(self):
        from types import SimpleNamespace

        class FakePage:
            def on(self, *_): pass
            async def goto(self, *_args, **_kwargs): pass

        class FakeContext:
            def __init__(self):
                self.pages = [FakePage()]
                self.callback = None
            def on(self, event, callback):
                if event == "close":
                    self.callback = callback
            async def close(self):
                self.pages = []
                if self.callback:
                    self.callback(self)

        class FakeChromium:
            async def launch_persistent_context(self, **_kwargs):
                return context

        context = FakeContext()
        profile = self.store.save(Profile(browser="chromium"))
        manager = SharedBrowserManager(self.store)
        manager._playwright = SimpleNamespace(chromium=FakeChromium())

        async def exercise():
            session = Session(profile)
            manager._sessions[profile.id] = session
            opening = asyncio.create_task(manager._open(session))
            try:
                await asyncio.wait_for(session.ready.wait(), timeout=5)
                self.assertTrue(manager.active(profile.id))
                self.assertFalse(opening.done())
                # Browser context closes spontaneously, not manager.stop().
                await context.close()
                await asyncio.wait_for(opening, timeout=5)
                self.assertFalse(manager.active(profile.id))
                self.assertEqual(manager.count(), 0)
                self.assertIsNone(manager.last_run(profile.id))
                # Prove the actual OS lease is released, not just the UI flag.
                with ProfileLease(self.store.base, profile.id):
                    pass
            finally:
                session.closed.set()
                await asyncio.wait_for(opening, timeout=5)
        asyncio.run(exercise())

    def test_browser_proxy_server_brackets_ipv6(self):
        from types import SimpleNamespace

        options = {}
        class FakePage:
            def on(self, *_): pass
            async def goto(self, *_args, **_kwargs): pass
        class FakeContext:
            pages = [FakePage()]
            def on(self, *_): pass
            async def close(self): pass
        class FakeChromium:
            async def launch_persistent_context(self, **kwargs):
                options.update(kwargs)
                return FakeContext()

        profile = self.store.save(Profile(
            browser="chromium", proxy_scheme="http",
            proxy_host="::1", proxy_port=8080))
        manager = SharedBrowserManager(self.store)
        manager._playwright = SimpleNamespace(chromium=FakeChromium())

        async def exercise():
            session = Session(profile)
            opening = asyncio.create_task(manager._open(session))
            try:
                await asyncio.wait_for(session.ready.wait(), timeout=5)
                self.assertEqual(options["proxy"]["server"], "http://[::1]:8080")
            finally:
                session.closed.set()
                await asyncio.wait_for(opening, timeout=5)
        asyncio.run(exercise())


class VisualWorkflowRegressions(unittest.TestCase):
    def test_invalid_json_does_not_get_overwritten_when_tab_reverted(self):
        from autumn_genlogin.ui import App
        from unittest.mock import MagicMock
        class Tabs:
            current=0
            app=None
            def index(self, _):return self.current
            def select(self, index):
                self.current=index
                self.app._sync_workflow_tabs() # simulate Tk's reentrant tab event
        class Text:
            value='{ "action": invalid user input'
            def get(self,*_):return self.value
            def delete(self,*_):self.value=''
            def insert(self,*args):self.value=args[-1]
        class Builder:
            _steps=[{"action":"goto","url":"https://example.com"}]
            def set_steps(self,steps):self._steps=steps
            def get_steps(self):return self._steps
        app=object.__new__(App)
        app.flow_tabs=Tabs()
        app.flow_tabs.app=app
        app.workflow=Text()
        app.builder=Builder()
        app.root=None
        before=app.workflow.value
        with patch("autumn_genlogin.ui.messagebox.showerror"):
            app._sync_workflow_tabs()
        self.assertEqual(app.flow_tabs.current, 1)
        self.assertEqual(app.workflow.value, before)


if __name__ == '__main__':
    unittest.main()
