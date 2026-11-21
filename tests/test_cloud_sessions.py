"""Real loopback TeamHub encrypted session handoff, roles and crash-safe download."""
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from autumn_genlogin.cloud_sessions import CloudSessionHandoff, MAX_ARCHIVE, _name
from autumn_genlogin.models import Profile
from autumn_genlogin.profile_backup import export_encrypted_profile, restore_encrypted_profile
from autumn_genlogin.storage import Store
from autumn_genlogin.team_sync import TeamHub, HubError, HubHTTPServer, CloudClient


class CloudSessionHandoffHTTPTests(unittest.TestCase):
    SHARED="a strong team transfer passphrase"
    BACKUP="a different session archive password"

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.hub=TeamHub(self.root/"team.sqlite3")
        self.server=HubHTTPServer(("127.0.0.1",0),self.hub)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        url=f"http://127.0.0.1:{self.server.server_port}"
        self.owner=CloudClient(url)
        self.viewer=CloudClient(url)
        self.owner.register("owner","long_owner_password_secret")
        self.viewer.register("viewer","long_viewer_password_secret")
        self.owner.login("owner","long_owner_password_secret")
        self.viewer.login("viewer","long_viewer_password_secret")
        self.team=self.owner.create_team("Transfer test")
        self.owner.set_member(self.team,"viewer","viewer")
        self.store=Store(self.root/"profile")
        self.profile=self.store.save(Profile(name="Synthetic QA Session",browser="chromium"))
        directory=self.store.profile_path(self.profile.id)
        directory.mkdir(parents=True)
        (directory/"Cookies").write_bytes(b"SYNTHETIC_SESSION_VALUE_NOT_PUBLIC")
        self.source=self.root/"profile.aglb"
        export_encrypted_profile(self.store,self.profile.id,self.source,self.BACKUP)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())
        self.tmp.cleanup()

    def test_owner_upload_viewer_download_and_offline_restore_new_profile(self):
        transfer=CloudSessionHandoff(self.owner)
        ident=transfer.upload(self.team,self.source,self.SHARED)
        self.assertEqual(len(ident),36)
        with closing(sqlite3.connect(self.root/"team.sqlite3")) as conn:
            storage=str(conn.execute("SELECT blob FROM documents").fetchall())
        self.assertNotIn("SYNTHETIC_SESSION_VALUE_NOT_PUBLIC",storage)
        self.assertNotIn("AUTUMN-LOCAL-PROFILE-BACKUP-1",storage)
        self.assertNotIn(self.BACKUP,storage)
        target=self.root/"download.aglb"
        result=CloudSessionHandoff(self.viewer).download(
            self.team,ident,target,self.SHARED)
        self.assertEqual(result,self.source.stat().st_size)
        self.assertEqual(target.read_bytes(),self.source.read_bytes())
        destination=Store(self.root/"restored")
        restored=restore_encrypted_profile(destination,target,self.BACKUP)
        self.assertEqual(restored.name,self.profile.name)
        self.assertNotEqual(restored.id,self.profile.id)
        self.assertEqual((destination.profile_path(restored.id)/"Cookies").read_bytes(),
                         b"SYNTHETIC_SESSION_VALUE_NOT_PUBLIC")

    def test_viewer_cannot_upload_and_manifest_is_immutable(self):
        with self.assertRaises(HubError) as e:
            CloudSessionHandoff(self.viewer).upload(self.team,self.source,self.SHARED)
        self.assertEqual(e.exception.status,403)
        ident=CloudSessionHandoff(self.owner).upload(self.team,self.source,self.SHARED)
        revision,doc=self.owner.pull(self.team,_name(ident),self.SHARED)
        with self.assertRaises(HubError) as conflict:
            self.owner.push(self.team,_name(ident),revision,doc,self.SHARED)
        self.assertEqual(conflict.exception.status,409)
        with self.assertRaises(HubError):
            self.owner.push(self.team,"unexpected-path",0,{},self.SHARED)

    def test_wrong_key_missing_chunk_and_existing_file_fail_closed(self):
        ident=CloudSessionHandoff(self.owner).upload(self.team,self.source,self.SHARED)
        target=self.root/"safe-download.aglb"
        with self.assertRaises(Exception):
            CloudSessionHandoff(self.viewer).download(self.team,ident,target,
                                                       "wrong shared passphrase")
        self.assertFalse(target.exists())
        target.write_bytes(b"PRESERVE_ME")
        with self.assertRaises(FileExistsError):
            CloudSessionHandoff(self.viewer).download(self.team,ident,target,self.SHARED)
        self.assertEqual(target.read_bytes(),b"PRESERVE_ME")
        target.unlink()
        with closing(sqlite3.connect(self.root/"team.sqlite3")) as conn:
            with conn:
                conn.execute("DELETE FROM documents WHERE team_id=? AND name=?",
                             (self.team,_name(ident,0)))
        with self.assertRaises(ValueError):
            CloudSessionHandoff(self.viewer).download(self.team,ident,target,self.SHARED)
        self.assertFalse(target.exists())

    def test_multichunk_archive_and_integrity_hash_enforced(self):
        # The test archive is genuinely encrypted; a large random local file
        # ensures chunking rather than relying on the small session fixture.
        folder=self.store.profile_path(self.profile.id)
        (folder/"LargeSynthetic").write_bytes(os.urandom(360*1024))
        extra=self.root/"chunked.aglb"
        export_encrypted_profile(self.store,self.profile.id,extra,self.BACKUP)
        self.assertGreater(extra.stat().st_size,256*1024)
        transfer=CloudSessionHandoff(self.owner)
        ident=transfer.upload(self.team,extra,self.SHARED)
        target=self.root/"multi.aglb"
        size=CloudSessionHandoff(self.viewer).download(
            self.team,ident,target,self.SHARED)
        self.assertEqual(size,extra.stat().st_size)
        self.assertEqual(target.read_bytes(),extra.read_bytes())

    def test_oversized_or_invalid_session_archive_rejected_without_upload(self):
        bad=self.root/"bad.aglb"
        bad.write_bytes(b"PLAINTEXT-DO-NOT-UPLOAD")
        with self.assertRaises(ValueError):
            CloudSessionHandoff(self.owner).upload(self.team,bad,self.SHARED)
        bad.write_bytes(b"not-archive" + os.urandom(100))
        with self.assertRaises(ValueError):
            CloudSessionHandoff(self.owner).upload(self.team,bad,self.SHARED)
        with self.assertRaises(ValueError):
            CloudSessionHandoff(self.viewer).download(
                self.team,"../invalid",self.root/"nothing.aglb",self.SHARED)
        with closing(sqlite3.connect(self.root/"team.sqlite3")) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
