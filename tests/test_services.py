"""Credential/DB sequencing tests with stubbed OS vault writes."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autumn_genlogin.models import Profile
from autumn_genlogin.services import save_profile_with_credentials
from autumn_genlogin.storage import Store


class ProfileServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))

    def test_failed_metadata_write_does_not_touch_secret(self):
        profile = Profile(proxy_scheme="http", proxy_host="localhost", proxy_port=4444, proxy_username="u")
        called = []
        with patch.object(self.store, "save", side_effect=PermissionError("disk unavailable")):
            with self.assertRaises(PermissionError):
                save_profile_with_credentials(self.store, profile, None, "password",
                                              set_secret=lambda *_: called.append("set"),
                                              delete_secret=lambda *_: called.append("delete"))
        self.assertEqual(called, [])

    def test_vault_failure_rolls_back_new_metadata(self):
        profile = Profile(proxy_scheme="http", proxy_host="localhost", proxy_port=4444, proxy_username="u")
        with self.assertRaises(PermissionError):
            save_profile_with_credentials(self.store, profile, None, "secret",
                                          set_secret=lambda *_: (_ for _ in ()).throw(PermissionError("vault unavailable")),
                                          delete_secret=lambda *_: None)
        self.assertEqual(self.store.all(), [])

    def test_vault_failure_restores_existing_metadata(self):
        previous = self.store.save(Profile(name="Original",proxy_scheme="http",proxy_host="localhost",proxy_port=4444,proxy_username="u"))
        edit = Profile(**previous.public_dict())
        edit.name = "Changed"
        with self.assertRaises(PermissionError):
            save_profile_with_credentials(self.store, edit, previous, "replacement",
                                          set_secret=lambda *_: (_ for _ in ()).throw(PermissionError("vault unavailable")),
                                          delete_secret=lambda *_: None)
        self.assertEqual(self.store.get(previous.id).name, "Original")

    def test_successful_secret_stored_after_db(self):
        profile = Profile(name="Test", proxy_scheme="http",proxy_host="localhost",proxy_port=4444,proxy_username="u")
        observed = []
        def secret_writer(profile_id, password):
            self.assertEqual(self.store.get(profile_id).name, "Test")
            observed.append(password)
        save_profile_with_credentials(self.store, profile, None, "example-secret",
                                      set_secret=secret_writer, delete_secret=lambda *_: None)
        self.assertEqual(observed, ["example-secret"])

if __name__ == "__main__":
    unittest.main()
