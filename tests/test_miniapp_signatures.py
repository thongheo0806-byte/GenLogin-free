"""Pinned Ed25519 Miniapp key continuity and local publisher-trust tests."""
from __future__ import annotations

import base64
import json
import io
import sys
from contextlib import redirect_stdout
from unittest.mock import patch
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from autumn_genlogin.miniapps import FORMAT, MiniAppLibrary
from autumn_genlogin.miniapp_signatures import (
    SIGNED_FORMAT, sign_package, verify_signed_package, publisher_fingerprint,
)
from autumn_genlogin.storage import Store


class SignedMiniappsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        self.store=Store(self.home/"profile")
        self.catalog=MiniAppLibrary(self.store)
        self.private=Ed25519PrivateKey.generate()
        self.manifest={
            "format":FORMAT,"name":"Local Example QA","version":"1.0.0",
            "description":"Review a synthetic publicly readable heading",
            "category":"QA",
            "workflow":[
                {"action":"goto","url":"https://example.com"},
                {"action":"wait_for","selector":"h1"},
                {"action":"extract_text","selector":"h1"}
            ]
        }
        self.signed=sign_package(self.manifest,self.private)

    def test_unsigned_legacy_still_installs_but_is_not_publisher_verified(self):
        record=self.catalog.install(self.manifest)
        self.assertEqual(record.signature_status,"unsigned")
        self.assertEqual(record.publisher_fingerprint,"")
        self.assertEqual(self.catalog.get(record.id),self.manifest)
        reopened=MiniAppLibrary(Store(self.home/"profile"))
        self.assertEqual(reopened.list()[0].signature_status,"unsigned")

    def test_trust_is_explicit_before_signed_import_and_rechecked_on_load(self):
        with self.assertRaisesRegex(ValueError,"not explicitly trusted"):
            self.catalog.install_signed(self.signed)
        self.assertEqual(self.catalog.list(),[])
        fp=publisher_fingerprint(self.signed["public_key"])
        self.assertEqual(self.catalog.trust_publisher("Synthetic QA publisher",
                                                      self.signed["public_key"]),fp)
        self.assertEqual(len(self.catalog.list_publishers()),1)
        saved=self.catalog.install_signed(self.signed)
        self.assertEqual(saved.publisher_fingerprint,fp)
        self.assertEqual(saved.signature_status,"trusted")
        self.assertEqual(self.catalog.get(saved.id),self.manifest)
        self.assertEqual(self.catalog.install_signed(self.signed).id,saved.id)
        reopened=MiniAppLibrary(Store(self.home/"profile"))
        self.assertEqual(reopened.list()[0].signature_status,"trusted")
        reopened.untrust_publisher(fp)
        self.assertEqual(reopened.list()[0].signature_status,"untrusted")
        with self.assertRaisesRegex(ValueError,"no longer locally trusted"):
            reopened.get(saved.id)
        self.assertEqual(reopened.trust_publisher("Synthetic QA publisher",
                                                  self.signed["public_key"]),fp)
        self.assertEqual(reopened.get(saved.id),self.manifest)
        reopened.remove(saved.id)
        self.assertEqual(reopened.list(),[])

    def test_valid_signature_does_not_prove_actual_publisher_identity(self):
        checked,fp,pub,sig=verify_signed_package(self.signed)
        self.assertEqual(checked,self.manifest)
        self.assertEqual(fp,publisher_fingerprint(pub))
        self.assertEqual(len(base64.b64decode(sig)),64)
        self.assertNotIn("real identity",self.signed)

    def test_tampered_workflow_key_signature_and_trailing_fields_fail(self):
        self.catalog.trust_publisher("Synthetic",self.signed["public_key"])
        changed=json.loads(json.dumps(self.signed))
        changed["manifest"]["workflow"].append({"action":"click","selector":"#unsafe"})
        invalids=[
            changed,
            {**self.signed,"signature":base64.b64encode(b"x"*64).decode()},
            {**self.signed,"public_key":base64.b64encode(b"z"*32).decode()},
            {**self.signed,"signature":"not-base64"},
            {**self.signed,"publisher":"claimed-verified-company"},
            {**self.signed,"format":"unspecified"},
        ]
        for case in invalids:
            with self.subTest(case=list(case)),self.assertRaises(ValueError):
                self.catalog.install_signed(case)
        self.assertEqual(self.catalog.list(),[])
        for invalid in ("", "not-base64",base64.b64encode(b"few").decode()):
            with self.subTest(key=invalid),self.assertRaises(ValueError):
                publisher_fingerprint(invalid)

    def test_same_pinned_name_cannot_silently_change_publisher_key(self):
        key2=Ed25519PrivateKey.generate()
        self.catalog.trust_publisher("First",self.signed["public_key"])
        alternate=sign_package({**self.manifest,"version":"1.0.1"},key2)
        self.catalog.trust_publisher("Other",alternate["public_key"])
        first=self.catalog.install_signed(self.signed)
        with self.assertRaisesRegex(ValueError,"pinned to another publisher"):
            self.catalog.install_signed(alternate)
        self.assertEqual([r.id for r in self.catalog.list()],[first.id])
        # An unsigned update may not impersonate any installed signed name.
        with self.assertRaisesRegex(ValueError,"unsigned updates are refused"):
            self.catalog.install({**self.manifest,"version":"2.0.0"})
        # Idempotent import of the exact signed content is still allowed.
        self.assertEqual(self.catalog.install(self.manifest).id,first.id)

    def test_db_attestation_corruption_detected_and_no_silent_downgrade(self):
        fp=self.catalog.trust_publisher("Test",self.signed["public_key"])
        signed=self.catalog.install_signed(self.signed)
        self.assertEqual(self.catalog.install(self.manifest).signature_status,"trusted")
        with self.store._connect() as conn:
            conn.execute("UPDATE miniapp_attestations SET signature=? WHERE miniapp_id=?",
                         (base64.b64encode(b"k"*64).decode(),signed.id))
        with self.assertRaisesRegex(ValueError,"signature is invalid"):
            self.catalog.get(signed.id)
        listing=self.catalog.list()
        self.assertEqual(len(listing),1)
        self.assertEqual(listing[0].signature_status,"invalid")
        self.assertEqual(len(self.catalog.list_publishers()),1)
        # A corrupt package can be removed without decoding its manifest.
        self.catalog.remove(signed.id)
        self.assertEqual(self.catalog.list(),[])

    def test_name_pin_persists_after_uninstall_and_explicit_trust_revocation(self):
        fp=self.catalog.trust_publisher("Original",self.signed["public_key"])
        saved=self.catalog.install_signed(self.signed)
        self.catalog.remove(saved.id)
        self.catalog.untrust_publisher(fp)
        self.assertEqual(self.catalog.list(),[])
        with self.assertRaisesRegex(ValueError,"unsigned updates are refused"):
            self.catalog.install({**self.manifest,"version":"1.0.2"})
        other=Ed25519PrivateKey.generate()
        replacement=sign_package({**self.manifest,"version":"1.0.3"},other)
        self.catalog.trust_publisher("Replacement",replacement["public_key"])
        with self.assertRaisesRegex(ValueError,"pinned to another publisher"):
            self.catalog.install_signed(replacement)
        # The durable pin survives reopening the database.
        reopened=MiniAppLibrary(Store(self.home/"profile"))
        with self.assertRaisesRegex(ValueError,"unsigned updates are refused"):
            reopened.install(self.manifest)

    def test_one_corrupt_miniapp_cannot_hide_another_valid_miniapp(self):
        first=self.catalog.install(self.manifest)
        second=self.catalog.install({**self.manifest,"name":"Other QA miniapp"})
        with self.store._connect() as conn:
            conn.execute("UPDATE miniapps SET manifest=? WHERE id=?",
                         ("{bad-json",first.id))
        listing=self.catalog.list()
        self.assertEqual([item.signature_status for item in listing],
                         ["invalid","unsigned"] if listing[0].id==first.id
                         else ["unsigned","invalid"])
        self.assertEqual(self.catalog.get(second.id)["name"],"Other QA miniapp")
        with self.assertRaises(ValueError):
            self.catalog.get(first.id)
        self.catalog.remove(first.id)
        self.assertEqual([item.id for item in self.catalog.list()],[second.id])

    def test_private_pem_signing_cli_preserves_existing_output_and_prints_only_public_key(self):
        from cryptography.hazmat.primitives import serialization
        from autumn_genlogin.miniapp_signatures import main
        private_file=self.home/"only-local-private.pem"
        private_file.write_bytes(self.private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        manifest_file=self.home/"manifest.json"
        manifest_file.write_text(json.dumps(self.manifest),encoding="utf-8")
        output=self.home/"signed.json"
        buffer=io.StringIO()
        with patch.object(sys,"argv",[
            "miniapp_signatures","sign",str(manifest_file),str(private_file),str(output)
        ]),redirect_stdout(buffer):
            result=main()
        self.assertEqual(result,0)
        saved=json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(saved["format"],SIGNED_FORMAT)
        self.assertEqual(verify_signed_package(saved)[0],self.manifest)
        original=output.read_bytes()
        with patch.object(sys,"argv",[
            "miniapp_signatures","sign",str(manifest_file),str(private_file),str(output)
        ]),redirect_stdout(io.StringIO()):
            self.assertEqual(main(),1,"CLI must not overwrite an existing package")
        self.assertEqual(output.read_bytes(),original)
        buffer=io.StringIO()
        with patch.object(sys,"argv",[
            "miniapp_signatures","public",str(private_file)
        ]),redirect_stdout(buffer):
            self.assertEqual(main(),0)
        self.assertIn(saved["public_key"],buffer.getvalue())
        self.assertIn(publisher_fingerprint(saved["public_key"]),buffer.getvalue())
        self.assertNotIn("BEGIN PRIVATE KEY",buffer.getvalue())

    def test_signed_json_file_import_and_validation_no_auto_execution(self):
        self.catalog.trust_publisher("Synthetic",self.signed["public_key"])
        source=self.home/"signed-miniapp.json"
        source.write_text(json.dumps(self.signed),encoding="utf-8")
        item=self.catalog.install_json(source)
        self.assertEqual(item.signature_status,"trusted")
        self.assertEqual(item.steps,3)
        self.assertEqual(item.origins,("https://example.com",))
        self.assertEqual(len(self.catalog.list()),1)
        # Import only adds an immutable JSON template; it does not launch a browser.
        with self.store._connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
