"""Storage corruption, socket lifetime, and quota attack regressions.

Fixtures contain synthetic metadata only; no real browser sessions or secrets.
"""
from __future__ import annotations

import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from autumn_genlogin.models import Profile
from autumn_genlogin.scheduler import ScheduleStore, Scheduler
from autumn_genlogin.storage import Store
from autumn_genlogin.team_sync import CloudClient, HubError, HubHTTPServer, TeamHub, encrypt_document


class CorruptSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "profile")
        profile = self.store.save(Profile(name="Audited fixture"))
        self.profile_id = profile.id
        self.schedules = ScheduleStore(self.store)
        self.workflow = [{"action": "wait", "seconds": 0}]

    def add_due(self):
        return self.schedules.add(
            self.profile_id, self.workflow,
            datetime.now(timezone.utc) - timedelta(minutes=1),
        )

    def corrupt(self, ident):
        with self.store._connect() as conn:
            conn.execute("UPDATE schedules SET workflow_json=? WHERE id=?", ("{broken-json", ident))

    def test_corrupt_row_is_quarantined_and_healthy_row_dispatches(self):
        bad, good = self.add_due(), self.add_due()
        self.corrupt(bad)
        jobs = self.schedules.claim_due()
        self.assertEqual([job.id for job in jobs], [good])
        statuses = {job.id: job for job in self.schedules.list()}
        self.assertFalse(statuses[bad].enabled)
        self.assertEqual(statuses[bad].last_status, "error")
        self.assertEqual(statuses[bad].last_error, "InvalidStoredWorkflow")
        self.assertEqual(statuses[bad].workflow, [])
        self.assertEqual(self.schedules.history(bad), [])
        self.assertEqual(len(self.schedules.history(good)), 1)
        self.assertEqual(self.schedules.claim_due(), [])

    def test_listing_corrupt_row_does_not_break_other_rows(self):
        bad, good = self.add_due(), self.add_due()
        self.corrupt(bad)
        jobs = {job.id: job for job in self.schedules.list()}
        self.assertEqual(jobs[bad].last_status, "error")
        self.assertFalse(jobs[bad].enabled)
        self.assertEqual(jobs[good].workflow, self.workflow)
        self.assertEqual([job.id for job in self.schedules.claim_due()], [good])

    def test_worker_stays_alive_after_corruption_and_runs_next_job(self):
        bad, good = self.add_due(), self.add_due()
        self.corrupt(bad)
        received = threading.Event()
        dispatched = []
        def consume(_pid, flow):
            dispatched.append(flow)
            received.set()
        worker = Scheduler(self.schedules, consume, interval=0.01)
        worker.start()
        try:
            self.assertTrue(received.wait(timeout=5))
            self.assertTrue(worker._thread.is_alive())
        finally:
            worker.stop()
        self.assertEqual(dispatched, [self.workflow])
        self.assertEqual(self.schedules.history(bad), [])
        self.assertEqual(len(self.schedules.history(good)), 1)


class TeamHubHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.hub = TeamHub(self.root / "team.sqlite3")
        self.server = HubHTTPServer(("127.0.0.1", 0), self.hub)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)
        self.assertFalse(self.worker.is_alive())
        self.temp.cleanup()

    def clients(self):
        owner, editor = CloudClient(self.url), CloudClient(self.url)
        owner.register("owner", "unique-test-owner-password")
        editor.register("editor", "unique-test-editor-password")
        owner.login("owner", "unique-test-owner-password")
        editor.login("editor", "unique-test-editor-password")
        team = owner.create_team("Synthetic team")
        owner.set_member(team, "editor", "editor")
        return owner, editor, team

    def test_rejects_fake_encrypted_envelopes_before_persisting(self):
        owner, editor, team = self.clients()
        name = f"session-{uuid4()}-00"
        invalid = [
            {"format": "AutumnGenLogin/encrypted-1"},
            {"format": "AutumnGenLogin/encrypted-1", "salt": "bad",
             "nonce": "bad", "ciphertext": "bad"},
            {"format": "AutumnGenLogin/encrypted-1", "salt": "AA==",
             "nonce": "AA==", "ciphertext": "AA=="},
        ]
        for envelope in invalid:
            with self.subTest(envelope=envelope), self.assertRaises(HubError) as exc:
                editor.request("PUT", f"/teams/{team}/documents/{name}",
                               {"revision": 0, "blob": envelope})
            self.assertEqual(exc.exception.status, 400)
        self.assertEqual(owner.list_sessions(team), [])

    def test_per_member_quota_admin_discovery_and_cleanup(self):
        owner, editor, team = self.clients()
        blob = encrypt_document({"synthetic": "fixture"}, "local-testing-passphrase")
        ids = [str(uuid4()) for _ in range(4)]
        def put(client, sid):
            return client.request(
                "PUT", f"/teams/{team}/documents/session-{sid}-00",
                {"revision": 0, "blob": blob},
            )["revision"]
        with patch("autumn_genlogin.team_sync.MAX_MEMBER_SESSION_DOCUMENTS", 2):
            self.assertEqual(put(editor, ids[0]), 1)
            self.assertEqual(put(editor, ids[1]), 1)
            with self.assertRaises(HubError) as exc:
                put(editor, ids[2])
            self.assertEqual(exc.exception.status, 413)
            # An abusive editor must not exhaust the owner's own quota.
            self.assertEqual(put(owner, ids[3]), 1)
            with self.assertRaises(HubError) as denied:
                editor.list_sessions(team)
            self.assertEqual(denied.exception.status, 403)
            listing = owner.list_sessions(team)
            self.assertEqual({item["session_id"] for item in listing},
                             {ids[0], ids[1], ids[3]})
            self.assertEqual(next(x for x in listing if x["session_id"] == ids[0])["uploaders"],
                             ["editor"])
            self.assertEqual(owner.revoke_session(team, ids[0])["deleted_documents"], 1)
            self.assertEqual(put(editor, ids[2]), 1)

    def test_stalled_header_clients_cannot_keep_server_close_blocked(self):
        extra_hub = TeamHub(self.root / "header.sqlite3")
        server = HubHTTPServer(("127.0.0.1", 0), extra_hub)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        sockets = []
        try:
            for _ in range(3):
                sock = socket.create_connection(("127.0.0.1", server.server_port), timeout=3)
                sock.sendall(b"POST /register HTTP/1.1\r\nHost: localhost\r\n")
                sockets.append(sock)
            time.sleep(0.1)
            start = time.monotonic()
            server.shutdown()
            server.server_close()
            self.assertLess(time.monotonic() - start, 3.5)
        finally:
            for sock in sockets:
                sock.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

    def test_migrates_old_document_table_without_losing_rows(self):
        legacy_path = self.root / "old.sqlite3"
        with sqlite3.connect(legacy_path) as conn:
            conn.execute(
                "CREATE TABLE documents(team_id TEXT NOT NULL,name TEXT NOT NULL,"
                "revision INTEGER NOT NULL,blob TEXT NOT NULL,PRIMARY KEY(team_id,name))"
            )
            conn.execute("INSERT INTO documents VALUES(?,?,?,?)",
                         ("old-team", "profiles", 1, '{"format":"legacy"}'))
        upgraded = TeamHub(legacy_path)
        with upgraded._db() as conn:
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(documents)")]
            self.assertIn("creator_id", columns)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
