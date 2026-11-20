"""Real encrypted profile backup/restore regression and malicious archive tests."""
from __future__ import annotations

import io
import json
import os
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from autumn_genlogin.locks import ProfileLease, ProfileBusyError
from autumn_genlogin.models import Profile
from autumn_genlogin.profile_backup import (
    MAGIC, FORMAT, MAX_METADATA, export_encrypted_profile, restore_encrypted_profile,
    _key,
)
from autumn_genlogin.storage import Store


class EncryptedProfileBackupTests(unittest.TestCase):
    passphrase="a unique strong backup passphrase for tests"

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Store(self.root/"local")
        self.profile=self.store.save(Profile(name="Browser session",
                            browser="chromium",group_name="Work",
                            proxy_scheme="http",proxy_host="example.org",
                            proxy_port=8080,proxy_username="account"))
        self.folder=self.store.profile_path(self.profile.id)
        (self.folder/"Default"/"Local Storage").mkdir(parents=True)
        (self.folder/"Default"/"Local Storage"/"db.txt").write_text(
            "fake-cookie-session-secret-value",encoding="utf-8")
        (self.folder/"Preferences").write_bytes(b"\x00\x01Hello\xff")
        self.destination=self.root/"session.aglb"

    def _export(self):
        return export_encrypted_profile(self.store,self.profile.id,self.destination,self.passphrase)

    def _archive(self, members, profile=None):
        """Construct synthetically encrypted malformed archives for import tests."""
        profile=profile or self.profile.public_dict()
        profile.update(proxy_scheme="",proxy_host="",proxy_port=0,
                       proxy_username="",created_at="",updated_at="")
        meta=json.dumps({"format":FORMAT,"profile":profile}).encode()
        plain=io.BytesIO()
        with tarfile.open(fileobj=plain,mode="w") as archive:
            manifest=tarfile.TarInfo("profile.json")
            manifest.size=len(meta)
            archive.addfile(manifest,io.BytesIO(meta))
            for name,kind,data in members:
                entry=tarfile.TarInfo(name)
                if kind=="symlink":
                    entry.type=tarfile.SYMTYPE
                    entry.linkname="../../escape"
                    archive.addfile(entry)
                else:
                    entry.size=len(data)
                    archive.addfile(entry,io.BytesIO(data))
        salt=os.urandom(16)
        nonce=os.urandom(12)
        encrypted=AESGCM(_key(self.passphrase,salt)).encrypt(nonce,plain.getvalue(),None)
        self.destination.write_bytes(MAGIC+salt+nonce+encrypted)

    def test_roundtrip_is_encrypted_and_imports_new_profile_without_vault_proxy(self):
        self.assertEqual(self._export(),2)
        raw=self.destination.read_bytes()
        self.assertTrue(raw.startswith(MAGIC))
        self.assertNotIn(b"fake-cookie-session-secret-value",raw)
        self.assertNotIn(b"example.org",raw)
        restored=restore_encrypted_profile(self.store,self.destination,self.passphrase)
        self.assertNotEqual(restored.id,self.profile.id)
        self.assertEqual(restored.name,self.profile.name)
        self.assertEqual(restored.group_name,"Work")
        self.assertEqual(restored.proxy_scheme,"")
        self.assertEqual(restored.proxy_username,"")
        self.assertEqual(self.store.get(restored.id).name,self.profile.name)
        self.assertEqual((self.store.profile_path(restored.id)/"Default"/"Local Storage"/"db.txt").read_text(),
                         "fake-cookie-session-secret-value")
        self.assertEqual((self.store.profile_path(restored.id)/"Preferences").read_bytes(),b"\x00\x01Hello\xff")
        self.assertEqual(len(self.store.all()),2)

    def test_wrong_passphrase_and_tamper_do_not_install_any_profile(self):
        self._export()
        with self.assertRaises(ValueError):
            restore_encrypted_profile(self.store,self.destination,"wrong passphrase 123")
        self.assertEqual(len(self.store.all()),1)
        raw=bytearray(self.destination.read_bytes())
        raw[len(MAGIC)+30] ^= 0x01
        self.destination.write_bytes(raw)
        with self.assertRaises(ValueError):
            restore_encrypted_profile(self.store,self.destination,self.passphrase)
        self.assertEqual(len(self.store.all()),1)
        self.assertFalse(any(self.store.browser_dir.glob(".import-*")))

    def test_archive_traversal_and_absolute_paths_are_blocked(self):
        for unsafe in ("browser/../../escape","/tmp/escape","browser/../other",
                       "browser/C:/windows","browser/CON.txt","browser/dir\\evil"):
            with self.subTest(unsafe=unsafe):
                self._archive([(unsafe,"file",b"data")])
                with self.assertRaises(ValueError):
                    restore_encrypted_profile(self.store,self.destination,self.passphrase)
                self.assertEqual(len(self.store.all()),1)
                self.assertFalse((self.root/"escape").exists())

    def test_archive_symlink_and_duplicate_casefold_names_are_blocked(self):
        self._archive([("browser/link","symlink",b"")])
        with self.assertRaises(ValueError):
            restore_encrypted_profile(self.store,self.destination,self.passphrase)
        self._archive([("browser/Alpha","file",b"a"),("browser/alpha","file",b"b")])
        with self.assertRaises(ValueError):
            restore_encrypted_profile(self.store,self.destination,self.passphrase)
        self.assertEqual(len(self.store.all()),1)

    def test_existing_file_never_overwritten(self):
        self.destination.write_text("keep original")
        with self.assertRaises(FileExistsError):
            self._export()
        self.assertEqual(self.destination.read_text(),"keep original")

    def test_refuses_unencrypted_backup_in_application_data(self):
        with self.assertRaises(ValueError):
            export_encrypted_profile(self.store,self.profile.id,self.store.base/"session.aglb",self.passphrase)

    def test_source_link_is_rejected_instead_of_followed(self):
        outside=self.root/"private-file"
        outside.write_text("not permitted")
        alias=self.folder/"suspicious"
        try:
            alias.symlink_to(outside)
        except (OSError,NotImplementedError):
            self.skipTest("filesystem does not allow symlink creation")
        with self.assertRaises(ValueError):
            self._export()
        self.assertFalse(self.destination.exists())

    def test_active_profile_lease_prevents_export(self):
        with ProfileLease(self.store.base,self.profile.id):
            with self.assertRaises(ProfileBusyError):
                self._export()
        self.assertFalse(self.destination.exists())

    def test_store_failure_cleans_staged_and_imported_files(self):
        self._export()
        with patch.object(self.store,"save",side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                restore_encrypted_profile(self.store,self.destination,self.passphrase)
        self.assertEqual(len(self.store.all()),1)
        self.assertEqual([p.name for p in self.store.browser_dir.iterdir()],[self.profile.id])

    def test_bad_manifest_rejected_even_when_archive_is_authenticated(self):
        tampered=self.profile.public_dict()
        tampered["name"]=""
        self._archive([],profile=tampered)
        with self.assertRaises(ValueError):
            restore_encrypted_profile(self.store,self.destination,self.passphrase)
        self.assertEqual(len(self.store.all()),1)


if __name__=="__main__":
    unittest.main()
