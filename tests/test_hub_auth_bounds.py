"""Structural timing and concurrency regressions, no timing-flaky thresholds."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from autumn_genlogin import team_sync as hubmod


class AuthenticationBoundsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.hub=hubmod.TeamHub(Path(self.temp.name)/"hub.sqlite3")
        self.hub.register("existing","synthetic-valid-password")

    def test_unknown_and_known_bad_password_use_same_current_kdf(self):
        original=hubmod._scrypt_key
        for username in ("existing","missing"):
            with patch.object(hubmod,"_scrypt_key",wraps=original) as derive:
                with self.assertRaises(hubmod.HubError) as caught:
                    self.hub.login(username,"synthetic-incorrect-password")
                self.assertEqual((caught.exception.status,caught.exception.message),
                                 (401,"Invalid credentials"))
                self.assertEqual(derive.call_count,1)
                self.assertEqual(derive.call_args.kwargs,
                    {"log_n":hubmod.CURRENT_SCRYPT_LOG_N,"dklen":64})

    def test_login_and_registration_share_fail_fast_capacity(self):
        held=[]
        try:
            for _ in range(hubmod.AUTH_KDF_SLOTS):
                self.assertTrue(hubmod._AUTH_SLOTS.acquire(blocking=False))
                held.append(True)
            with patch.object(hubmod,"_scrypt_key") as derive:
                for operation in (
                    lambda:self.hub.login("existing","synthetic-valid-password"),
                    lambda:self.hub.login("missing","synthetic-valid-password"),
                    lambda:self.hub.register("newuser","synthetic-valid-password"),
                ):
                    with self.assertRaises(hubmod.HubError) as caught:
                        operation()
                    self.assertEqual(caught.exception.status,503)
                derive.assert_not_called()
        finally:
            for _ in held:
                hubmod._AUTH_SLOTS.release()
        self.assertTrue(self.hub.login("existing","synthetic-valid-password"))

    def test_auth_slot_released_on_derivation_failure(self):
        with patch.object(hubmod,"_scrypt_key",side_effect=RuntimeError("fixture")):
            with self.assertRaises(RuntimeError):
                self.hub.login("existing","synthetic-valid-password")
        held=[]
        try:
            for _ in range(hubmod.AUTH_KDF_SLOTS):
                self.assertTrue(hubmod._AUTH_SLOTS.acquire(blocking=False))
                held.append(True)
        finally:
            for _ in held:
                hubmod._AUTH_SLOTS.release()


if __name__=="__main__":
    unittest.main()
