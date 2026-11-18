import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from autumn_genlogin.diagnostics import audit_store
from autumn_genlogin.locks import ProfileBusyError, ProfileLease
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class DiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))

    def test_fresh_store_passes(self):
        report = audit_store(self.store)
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["schema"], "AutumnGenLogin/diagnostics/1")

    def test_orphaned_directory_warns_but_never_deletes(self):
        orphan = self.store.browser_dir / str(uuid4())
        orphan.mkdir()
        report = audit_store(self.store)
        self.assertEqual(next(c["status"] for c in report["checks"] if c["name"] == "orphaned_profile_data"), "warn")
        self.assertTrue(orphan.exists())

    def test_report_contains_no_proxy_credentials(self):
        self.store.save(Profile(name="redacted", proxy_scheme="http", proxy_host="example.com", proxy_port=8000, proxy_username="SECRET_NAME"))
        content = json.dumps(audit_store(self.store))
        self.assertNotIn("SECRET_NAME", content)
        self.assertNotIn("example.com", content)

    def test_detects_corrupt_db_without_network(self):
        self.store.db.write_bytes(b"invalid sqlite file")
        report = audit_store(self.store)
        self.assertGreater(report["summary"]["failed"], 0)

    def test_double_lock_fails(self):
        p = self.store.save(Profile(name="Lock test"))
        with ProfileLease(self.store.base, p.id):
            with self.assertRaises(ProfileBusyError):
                with ProfileLease(self.store.base, p.id):
                    pass

    def test_locked_profile_cannot_be_deleted(self):
        p = self.store.save(Profile(name="Open profile"))
        with ProfileLease(self.store.base, p.id):
            with self.assertRaises(ProfileBusyError):
                self.store.delete(p.id)
        self.assertEqual(self.store.get(p.id).name, "Open profile")
        self.store.delete(p.id)
        with self.assertRaises(KeyError):
            self.store.get(p.id)

    def test_lock_id_rejects_traversal(self):
        with self.assertRaises(ValueError):
            ProfileLease(self.store.base, "../../../another-place")


if __name__ == "__main__":
    unittest.main()
