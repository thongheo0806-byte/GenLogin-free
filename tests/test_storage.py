import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import UUID

from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "source")

    def test_create_read_update_clone_delete(self):
        a = self.store.save(Profile(name="Alpha"))
        self.assertEqual(self.store.get(a.id).name, "Alpha")
        a.name = "Beta"
        self.store.save(a)
        self.assertEqual(len(self.store.all()), 1)
        b = self.store.clone(a.id)
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(b.name, "Beta (copy)")
        self.store.delete(a.id)
        self.assertEqual(len(self.store.all()), 1)
        with self.assertRaises(KeyError):
            self.store.get(a.id)

    def test_public_read_and_transaction_contexts_preserve_commit_rollback(self):
        profile=self.store.save(Profile(name="Public API fixture"))
        with self.store.read() as conn:
            row=conn.execute("SELECT name FROM profiles WHERE id=?",
                             (profile.id,)).fetchone()
            self.assertEqual(row["name"],"Public API fixture")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE profiles SET name=? WHERE id=?",
                             ("MUST_NOT_WRITE",profile.id))
        self.assertEqual(self.store.get(profile.id).name,"Public API fixture")
        with self.store.transaction() as conn:
            conn.execute("UPDATE profiles SET name=? WHERE id=?",
                         ("Committed name",profile.id))
        self.assertEqual(self.store.get(profile.id).name,"Committed name")
        with self.assertRaisesRegex(RuntimeError,"simulate rollback"):
            with self.store.transaction() as conn:
                conn.execute("UPDATE profiles SET name=? WHERE id=?",
                             ("Rolled back",profile.id))
                raise RuntimeError("simulate rollback")
        self.assertEqual(self.store.get(profile.id).name,"Committed name")

    def test_metadata_export_sanitizes_sessions(self):
        p = self.store.save(Profile(name="Saved", proxy_scheme="http", proxy_host="example.com", proxy_port=8888, proxy_username="alice"))
        folder = self.store.profile_path(p.id)
        folder.mkdir()
        (folder / "cookies").write_text("SECRET-CONSENT-TOKEN")
        export = Path(self.tmp.name) / "profiles.json"
        self.store.export_metadata(export)
        blob = export.read_text()
        self.assertNotIn("SECRET-CONSENT-TOKEN", blob)
        self.assertNotIn("proxy_password", blob)
        second = Store(Path(self.tmp.name) / "destination")
        second.import_metadata(export)
        imported = second.all()[0]
        self.assertNotEqual(imported.id, p.id)
        self.assertEqual(imported.name, "Saved")
        self.assertFalse(second.profile_path(imported.id).exists())

    def test_invalid_import_does_not_partially_import(self):
        source = Path(self.tmp.name) / "bad.json"
        source.write_text(json.dumps({"format": "AutumnGenLogin/1", "profiles": [Profile(name="Okay").public_dict(), {"name": "Broken", "start_url": "file:///local"}]}))
        with self.assertRaises((ValueError, TypeError)):
            self.store.import_metadata(source)
        self.assertEqual(self.store.all(), [])

    def test_uuid_blocks_path_traversal(self):
        with self.assertRaises(ValueError):
            self.store.profile_path("../../external")

    def test_backup(self):
        self.store.save(Profile(name="Original"))
        target = Path(self.tmp.name) / "backup.sqlite3"
        self.store.backup_database(target)
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
