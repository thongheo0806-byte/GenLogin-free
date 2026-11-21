"""Local Miniapp manifest, storage and security regressions."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from autumn_genlogin.miniapps import FORMAT, MiniAppLibrary, validate_miniapp
from autumn_genlogin.storage import Store


class MiniappsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/"store")
        self.lib=MiniAppLibrary(self.store)
        self.example={
            "format":FORMAT,"name":"Safe QA Inspector",
            "version":"1.0.0","category":"QA",
            "description":"Visits a public test website and reads heading",
            "workflow":[
                {"action":"goto","url":"https://example.com"},
                {"action":"wait_for","selector":"h1"},
                {"action":"extract_text","selector":"h1"}
            ]
        }

    def test_reviewed_manifest_roundtrip_idempotent_and_persistent(self):
        item=self.lib.install(self.example)
        self.assertEqual(item.name,"Safe QA Inspector")
        self.assertEqual(item.origins,("https://example.com",))
        self.assertEqual(item.steps,3)
        self.assertEqual(self.lib.install(self.example).id,item.id)
        self.assertEqual(len(self.lib.list()),1)
        doc=self.lib.get(item.id)
        self.assertEqual(doc,self.example)
        doc["workflow"][0]["url"]="https://changed.example"
        self.assertEqual(self.lib.get(item.id)["workflow"][0]["url"],
                         "https://example.com")
        reopened=MiniAppLibrary(Store(self.root/"store"))
        self.assertEqual([i.id for i in reopened.list()],[item.id])
        reopened.remove(item.id)
        self.assertEqual(self.lib.list(),[])

    def test_rejects_package_version_replacement_without_review(self):
        item=self.lib.install(self.example)
        altered=json.loads(json.dumps(self.example))
        altered["workflow"].append({"action":"click","selector":"#danger"})
        with self.assertRaisesRegex(ValueError,"incompatible miniapp"):
            self.lib.install(altered)
        self.assertEqual(self.lib.get(item.id),self.example)
        altered["version"]="1.0.1"
        self.assertNotEqual(self.lib.install(altered).id,item.id)
        self.assertEqual(len(self.lib.list()),2)

    def test_untrusted_code_and_secret_bearing_values_are_blocked(self):
        changes=[
            {"workflow":[{"action":"execute_script","code":"alert(1)"}]},
            {"workflow":[{"action":"fill","selector":"#pass","text":"secret123"}]},
            {"workflow":[{"action":"select_option","selector":"#list","value":"pii"}]},
            {"workflow":[{"action":"goto","url":"https://example.com/?access_token=secret"}]},
            {"workflow":[{"action":"goto","url":"https://example.com/#token"}]},
            {"workflow":[{"action":"goto","url":"http://example.com"}]},
            {"workflow":[{"action":"goto","url":"file:///etc/shadow"}]},
            {"workflow":[]},
            {"category":"Unreviewed"},
            {"format":"unknown"},
            {"version":"bad-version"},
            {"description":"injected\ncommands"},
            {"extra":"unapproved"},
        ]
        for change in changes:
            with self.subTest(change=change):
                doc={**self.example,**change}
                with self.assertRaises((ValueError,TypeError)):
                    self.lib.install(doc)
        self.assertEqual(self.lib.list(),[])

    def test_approved_loopback_origin_and_redacted_select_value(self):
        doc={**self.example,
             "workflow":[
                 {"action":"goto","url":"http://127.0.0.1:8123/test"},
                 {"action":"fill","selector":"#input","text":""},
                 {"action":"select_option","selector":"#selector",
                  "value":"REVIEW_OPTION"}
             ]}
        info=self.lib.install(doc)
        self.assertEqual(info.origins,("http://127.0.0.1:8123",))

    def test_json_import_is_not_executable_and_rejects_symlinks_or_oversize(self):
        src=self.root/"workflow.json"
        src.write_text(json.dumps(self.example),encoding="utf-8")
        info=self.lib.install_json(src)
        self.assertEqual(info.steps,3)
        with self.assertRaises(ValueError):
            self.lib.install_json(self.root/"missing.json")
        src.write_text("X"*65537)
        with self.assertRaisesRegex(ValueError,"64 KiB"):
            self.lib.install_json(src)
        outside=self.root/"external.json"
        outside.write_text(json.dumps(self.example))
        alias=self.root/"alias.json"
        try:alias.symlink_to(outside)
        except (OSError,NotImplementedError):
            self.skipTest("Symlinks unavailable")
        with self.assertRaisesRegex(ValueError,"ordinary JSON"):
            self.lib.install_json(alias)

    def test_database_tampering_detected_before_loading(self):
        item=self.lib.install(self.example)
        modified=json.dumps({**self.example,"description":"Changed after import"})
        with self.store._connect() as conn:
            conn.execute("UPDATE miniapps SET manifest=? WHERE id=?",(modified,item.id))
        with self.assertRaisesRegex(ValueError,"integrity check"):
            self.lib.get(item.id)


if __name__=="__main__":
    unittest.main()
