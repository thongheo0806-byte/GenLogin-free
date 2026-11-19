"""No external network: actual localhost HTTP API plus AES-GCM sync tests."""
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from autumn_genlogin.team_sync import (TeamHub, HubError, HubHTTPServer, CloudClient,
     encrypt_document, decrypt_document, safe_profile_metadata, merge_safe_profiles)
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class EncryptionTests(unittest.TestCase):
    def test_aesgcm_roundtrip_and_wrong_key(self):
        doc={"name":"Autumn","profiles":[{"id":"one"}]}
        blob=encrypt_document(doc,"strong shared passphrase")
        self.assertNotIn("one",json.dumps(blob))
        self.assertEqual(decrypt_document(blob,"strong shared passphrase"),doc)
        with self.assertRaises(Exception):decrypt_document(blob,"wrong passphrase")

    def test_ciphertext_tampering_detected(self):
        blob=encrypt_document({"name":"secret"},"strong shared passphrase")
        text=blob["ciphertext"]
        blob["ciphertext"]=("A" if text[0]!="A" else "B")+text[1:]
        with self.assertRaises(Exception):decrypt_document(blob,"strong shared passphrase")

    def test_safe_metadata_drops_proxy_credentials(self):
        with tempfile.TemporaryDirectory() as base:
            store=Store(Path(base))
            profile=store.save(Profile(name="Test",proxy_scheme="http",proxy_host="proxy.example",proxy_port=8080,proxy_username="sensitive"))
            doc=safe_profile_metadata(store)
            self.assertNotIn("proxy",json.dumps(doc))
            local=Store(Path(base)/"other")
            merge_safe_profiles(local,doc)
            self.assertEqual(local.get(profile.id).name,"Test")
            self.assertEqual(local.get(profile.id).proxy_username,"")
            # Later sync must not silently overwrite local proxy secrets.
            existing=local.get(profile.id);existing.proxy_scheme="http";existing.proxy_host="localhost";existing.proxy_port=8000
            local.save(existing)
            merge_safe_profiles(local,doc)
            self.assertEqual(local.get(profile.id).proxy_host,"localhost")


class TeamHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        hub=TeamHub(Path(self.tmp.name)/"team.sqlite3")
        self.server=HubHTTPServer(("127.0.0.1",0),hub)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base=f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        # shutdown only stops serve_forever; server_close joins all non-daemon
        # request handlers before Windows is asked to delete its SQLite file.
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), "Team hub listener did not exit")
        self.tmp.cleanup()

    def test_roles_conflicts_and_encrypted_document(self):
        alice=CloudClient(self.base)
        bob=CloudClient(self.base)
        alice.register("alice","alice_secure_password_123")
        bob.register("bob","bob_secure_password_123")
        alice.login("alice","alice_secure_password_123")
        bob.login("bob","bob_secure_password_123")
        team=alice.create_team("My team")
        doc={"format":"AutumnGenLogin/profile-metadata-1","profiles":[]}
        with self.assertRaises(HubError):bob.pull(team,"profiles","shared passphrase_123")
        alice.set_member(team,"bob","viewer")
        self.assertEqual(bob.members(team)[1]["role"],"viewer")
        with self.assertRaises(HubError) as refusal:
            bob.push(team,"profiles",0,doc,"shared passphrase_123")
        self.assertEqual(refusal.exception.status,403)
        self.assertEqual(alice.push(team,"profiles",0,doc,"shared passphrase_123"),1)
        rev,actual=bob.pull(team,"profiles","shared passphrase_123")
        self.assertEqual((rev,actual),(1,doc))
        with self.assertRaises(HubError) as conflict:
            alice.push(team,"profiles",0,doc,"shared passphrase_123")
        self.assertEqual(conflict.exception.status,409)
        alice.set_member(team,"bob","editor")
        self.assertEqual(bob.push(team,"profiles",1,doc,"shared passphrase_123"),2)
        with self.assertRaises(HubError):bob.set_member(team,"alice","admin")
        # Server disk cannot contain plaintext profile data.
        with sqlite3.connect(Path(self.tmp.name)/"team.sqlite3") as c:
            raw=c.execute("SELECT blob FROM documents").fetchone()[0]
            self.assertNotIn("profile-metadata-1",raw)

    def test_remote_http_rejected(self):
        with self.assertRaises(ValueError):CloudClient("http://example.com")
        with self.assertRaises(ValueError):HubHTTPServer(("0.0.0.0",0),TeamHub(Path(self.tmp.name)/"other.sqlite"))


if __name__=="__main__":unittest.main()
