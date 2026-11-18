"""Trusted-content boundaries for local developer extensions; no network needed."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from autumn_genlogin.extensions import ExtensionLibrary
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "home")
        self.library = ExtensionLibrary(self.store)
        self.source = self.root / "example"
        self.source.mkdir()
        (self.source / "manifest.json").write_text(json.dumps({
            "manifest_version": 3, "name": "Demo", "version": "0.1",
            "permissions": ["storage"], "host_permissions": ["https://example.com/*"]
        }))
        (self.source / "background.js").write_text("// harmless local test extension")

    def test_import_requires_explicit_attach_and_chromium(self):
        item = self.library.install_folder(self.source)
        self.assertEqual(item.permissions, ("storage",))
        self.assertEqual(item.host_permissions, ("https://example.com/*",))
        chrome = self.store.save(Profile(name="regular", browser="chrome"))
        with self.assertRaisesRegex(ValueError, "Chromium"):
            self.library.attach(chrome.id, item.id)
        chromium = self.store.save(Profile(name="opt in", browser="chromium"))
        self.assertEqual(self.library.paths_for(chromium.id), [])
        self.library.attach(chromium.id, item.id)
        self.assertEqual(len(self.library.paths_for(chromium.id)), 1)
        self.library.detach(chromium.id, item.id)
        self.assertEqual(self.library.paths_for(chromium.id), [])
        self.library.remove(item.id)
        self.assertEqual(self.library.list(), [])

    def test_rejects_zip_slip_and_symlink(self):
        zip_file = self.root / "attack.zip"
        with zipfile.ZipFile(zip_file, "w") as f:
            f.writestr("../escape.txt", "bad")
            f.writestr("manifest.json", (self.source / "manifest.json").read_text())
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.library.install_zip(zip_file)
        self.assertFalse((self.library.directory / "escape.txt").exists())

    def test_rejects_non_v3_or_malformed_extensions(self):
        (self.source / "manifest.json").write_text(json.dumps({"manifest_version": 2, "name": "old", "version": "1"}))
        with self.assertRaisesRegex(ValueError, "Manifest V3"):
            self.library.install_folder(self.source)
        self.assertEqual(self.library.list(), [])

    def test_zip_install_honors_permissions_and_cleans_db_on_profile_delete(self):
        archive = self.root / "safe.zip"
        with zipfile.ZipFile(archive, "w") as f:
            for file in self.source.iterdir():
                f.write(file, arcname=file.name)
        item = self.library.install_zip(archive)
        profile = self.store.save(Profile(browser="chromium"))
        self.library.attach(profile.id, item.id)
        self.assertEqual(self.library.attached_ids(profile.id), [item.id])
        self.store.delete(profile.id)
        self.assertEqual(self.library.attached_ids(profile.id), [])

    def test_prevents_archive_oversize(self):
        import autumn_genlogin.extensions as mod
        archive = self.root / "big.zip"
        with zipfile.ZipFile(archive, "w") as f:
            f.write(self.source / "manifest.json", "manifest.json")
            f.writestr("big.txt", b"a" * (mod.MAX_SINGLE_FILE + 1))
        with self.assertRaisesRegex(ValueError, "too large"):
            self.library.install_zip(archive)


if __name__ == "__main__":
    unittest.main()
