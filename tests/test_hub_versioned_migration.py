"""Versioned envelope migration and HTTP resource guard regressions."""
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from autumn_genlogin import team_sync as mod


class HubMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.hub=mod.TeamHub(Path(self.temp.name)/"hub.sqlite3")
        self.actor=self.hub.register("owner","synthetic-owner-password")
        self.team=self.hub.create_team(self.actor,"fixture")
        self.passphrase="synthetic-shared-passphrase"

    def legacy(self,doc):
        salt=b"0123456789abcdef"
        nonce=b"0123456789ab"
        key=mod._scrypt_key(self.passphrase,salt,log_n=14)
        return {"format":mod.FORMAT,"salt":mod._b64(salt),
                "nonce":mod._b64(nonce),"ciphertext":mod._b64(
                    AESGCM(key).encrypt(nonce,json.dumps(doc).encode(),mod.FORMAT.encode()))}

    def test_legacy_read_upgrade_and_no_downgrade(self):
        old=self.legacy({"version":"legacy"})
        self.assertEqual(self.hub.write_document(self.actor,self.team,"profiles",0,old),1)
        self.assertEqual(mod.decrypt_document(self.hub.read_document(self.actor,self.team,"profiles")["blob"],self.passphrase),{"version":"legacy"})
        upgraded=mod.encrypt_document({"version":"upgraded"},self.passphrase)
        self.assertEqual(self.hub.write_document(self.actor,self.team,"profiles",1,upgraded),2)
        with self.assertRaises(mod.HubError) as denied:
            self.hub.write_document(self.actor,self.team,"profiles",2,old)
        self.assertEqual(denied.exception.status,409)
        current=self.hub.read_document(self.actor,self.team,"profiles")
        self.assertEqual(current,{"revision":2,"blob":upgraded})

    def test_indexed_archive_listing_and_revocation(self):
        session_id=str(uuid4())
        second_id=str(uuid4())
        blob=mod.encrypt_document({"fixture":True},self.passphrase)
        for name in (f"session-{session_id}-00",f"session-{session_id}-manifest",
                     f"session-{second_id}-00"):
            self.hub.write_document(self.actor,self.team,name,0,blob)
        self.hub.write_document(self.actor,self.team,"profiles",0,blob)
        entries={item["session_id"]:item for item in self.hub.list_sessions(self.actor,self.team)}
        self.assertEqual(entries[session_id]["documents"],2)
        self.assertTrue(entries[session_id]["has_manifest"])
        self.assertEqual(self.hub.revoke_session(self.actor,self.team,session_id),2)
        self.assertEqual([item["session_id"] for item in self.hub.list_sessions(self.actor,self.team)],[second_id])
        self.assertEqual(self.hub.read_document(self.actor,self.team,"profiles")["revision"],1)

    def test_old_hub_error_explains_upgrade_without_retry(self):
        client=mod.CloudClient("http://127.0.0.1:1")
        with patch.object(client,"request",side_effect=mod.HubError(400,"Invalid encrypted document envelope")) as request:
            with self.assertRaisesRegex(mod.HubError,"upgrade Hub"):
                client.push(self.team,"profiles",0,{"fixture":True},self.passphrase)
            self.assertEqual(request.call_count,1)

    def test_handler_capacity_rejects_before_spawning_thread(self):
        server=mod.HubHTTPServer(("127.0.0.1",0),self.hub)
        self.addCleanup(server.server_close)
        held=[]
        try:
            for _ in range(mod.MAX_HTTP_HANDLERS):
                self.assertTrue(server._handler_slots.acquire(blocking=False))
                held.append(True)
            with patch.object(server,"shutdown_request") as shutdown, patch.object(
                    mod.ThreadingHTTPServer,"process_request") as spawn:
                request=object()
                server.process_request(request,("127.0.0.1",0))
                shutdown.assert_called_once_with(request)
                spawn.assert_not_called()
        finally:
            for _ in held:
                server._handler_slots.release()

    def test_malformed_unicode_login_has_uniform_401(self):
        for name,password in (("owner","\ud800"),("\ud800abc","wrong")):
            with self.assertRaises(mod.HubError) as denied:
                self.hub.login(name,password)
            self.assertEqual(denied.exception.status,401)


if __name__=="__main__":
    unittest.main()
