"""Team Hub versioned scrypt regression and legacy backward compatibility.

All test secrets are synthetic. No real credentials or external services.
"""
from __future__ import annotations

import base64
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import secrets
import sqlite3
import tempfile
import unittest
from pathlib import Path

from autumn_genlogin.team_sync import (
    CURRENT_SCRYPT_LOG_N, FORMAT, HubError, TeamHub,
    _validate_encrypted_envelope, decrypt_document, encrypt_document,
)


class EncryptedDocumentKDFTests(unittest.TestCase):
    PASSPHRASE="synthetic-shared-passphrase"

    def test_new_document_records_and_authenticates_work_factor(self):
        original={"format":"synthetic", "profiles":[{"name":"Private local QA"}]}
        blob=encrypt_document(original,self.PASSPHRASE)
        self.assertEqual(blob["kdf"],{"name":"scrypt","log_n":CURRENT_SCRYPT_LOG_N,
                                      "r":8,"p":1})
        self.assertEqual(CURRENT_SCRYPT_LOG_N,15)
        _validate_encrypted_envelope(blob)
        self.assertEqual(decrypt_document(blob,self.PASSPHRASE),original)
        for change in (
            {"log_n":14}, {"log_n":16}, {"r":16}, {"p":2},
        ):
            modified=deepcopy(blob)
            modified["kdf"].update(change)
            with self.subTest(change=change),self.assertRaises(Exception):
                decrypt_document(modified,self.PASSPHRASE)
        self.assertNotIn("Private local QA",json.dumps(blob))

    def test_untrusted_hub_rejects_unbounded_or_invalid_kdf_headers(self):
        blob=encrypt_document({"synthetic":"only"} ,self.PASSPHRASE)
        for broken in (
            {"log_n":1}, {"log_n":100}, {"log_n":True},
            {"r":True}, {"p":0}, {"name":"pbkdf2"},
            {"extra":1},
        ):
            modified=deepcopy(blob)
            modified["kdf"].update(broken)
            with self.subTest(broken=broken),self.assertRaises(HubError) as denied:
                _validate_encrypted_envelope(modified)
            self.assertEqual(denied.exception.status,400)

    def test_legacy_unversioned_encrypted_document_still_decrypts(self):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        salt,nonce=secrets.token_bytes(16),secrets.token_bytes(12)
        key=hashlib.scrypt(self.PASSPHRASE.encode(),salt=salt,
                           n=2**14,r=8,p=1,dklen=32)
        original={"before":"KDF migration"}
        ciphertext=AESGCM(key).encrypt(
            nonce,json.dumps(original).encode(),FORMAT.encode())
        old={"format":FORMAT,
             "salt":base64.b64encode(salt).decode(),
             "nonce":base64.b64encode(nonce).decode(),
             "ciphertext":base64.b64encode(ciphertext).decode()}
        _validate_encrypted_envelope(old)
        self.assertEqual(decrypt_document(old,self.PASSPHRASE),original)
        self.assertNotIn("kdf",old)


class HubPasswordUpgradeTests(unittest.TestCase):
    def test_existing_hub_user_login_rehashes_legacy_password(self):
        with tempfile.TemporaryDirectory() as home:
            path=Path(home)/"legacy-users.sqlite3"
            salt=secrets.token_bytes(16)
            password="synthetic-test-login-password"
            digest=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1)
            # Old DB schema contained no work-factor column.
            with closing(sqlite3.connect(path)) as conn:
                with conn:
                    conn.execute(
                        "CREATE TABLE users (id TEXT PRIMARY KEY, "
                        "username TEXT NOT NULL UNIQUE, "
                        "salt BLOB NOT NULL,password_hash BLOB NOT NULL)")
                    conn.execute("INSERT INTO users VALUES (?,?,?,?)",
                                 ("old-user","legacytester",salt,digest))
            hub=TeamHub(path)
            with closing(hub._db()) as conn:
                row=conn.execute("SELECT * FROM users WHERE username=?",
                                 ("legacytester",)).fetchone()
                self.assertEqual(row["password_kdf_log_n"],14)
            with self.assertRaises(HubError) as incorrect:
                hub.login("legacytester","wrong-test-password")
            self.assertEqual(incorrect.exception.status,401)
            hub.login("legacytester",password)
            with closing(hub._db()) as conn:
                upgraded=conn.execute(
                    "SELECT * FROM users WHERE username=?",("legacytester",)).fetchone()
                self.assertEqual(upgraded["password_kdf_log_n"],15)
                self.assertNotEqual(upgraded["salt"],salt)
                self.assertNotEqual(upgraded["password_hash"],digest)
                self.assertEqual(upgraded["id"],"old-user")
            # Subsequent successful logins must not downgrade or rehash again.
            hub.login("legacytester",password)
            with closing(hub._db()) as conn:
                persisted=conn.execute("SELECT * FROM users WHERE username=?",
                                       ("legacytester",)).fetchone()
                self.assertEqual(persisted["salt"],upgraded["salt"])
            with self.assertRaises(HubError):
                hub.login("legacytester","wrong-test-password")

    def test_newly_registered_user_stores_upgraded_scrypt_factor(self):
        with tempfile.TemporaryDirectory() as home:
            hub=TeamHub(Path(home)/"fresh.sqlite3")
            ident=hub.register("synthetic_new","synthetic-registration-pass")
            with closing(hub._db()) as conn:
                row=conn.execute(
                    "SELECT password_kdf_log_n,password_hash FROM users "
                    "WHERE username=?",("synthetic_new",)).fetchone()
            self.assertEqual(row["password_kdf_log_n"],CURRENT_SCRYPT_LOG_N)
            self.assertEqual(len(row["password_hash"]),64)
            token=hub.login("synthetic_new","synthetic-registration-pass")
            self.assertEqual(hub.identity(token),ident)


if __name__=="__main__":
    unittest.main()
