"""Offline MV3 package update/rollback security and transactional regressions."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from autumn_genlogin.extensions import ExtensionLibrary
from autumn_genlogin.locks import ProfileBusyError, ProfileLease
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class ExtensionUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Store(self.root/"store")
        self.lib=ExtensionLibrary(self.store)
        self.profile_ids=[self.store.save(Profile(name=f"test {n}",browser="chromium")).id
                          for n in range(2)]
        self.old_src=self.root/"v1"
        self.old_src.mkdir()
        self._manifest(self.old_src, "Demo", "1.0",["storage"],["https://example.org/*"])
        self.old=self.lib.install_folder(self.old_src)
        for pid in self.profile_ids:
            self.lib.attach(pid,self.old.id)
        self.archive=self.root/"new.zip"
        self._zip(self.archive,"Demo","2.0",["storage","tabs"],["https://example.org/*","https://new.example/*"])

    def _manifest(self,root,name,version,permissions,hosts):
        (root/"manifest.json").write_text(json.dumps({
            "manifest_version":3,"name":name,"version":version,
            "permissions":permissions,"host_permissions":hosts}),encoding="utf8")
        (root/"background.js").write_text("// fixture",encoding="utf8")

    def _zip(self,target,name,version,permissions,hosts):
        data={"manifest_version":3,"name":name,"version":version,
              "permissions":permissions,"host_permissions":hosts}
        with zipfile.ZipFile(target,"w") as z:
            z.writestr("manifest.json",json.dumps(data))
            z.writestr("background.js","// fixture v2")

    def test_update_requires_review_and_migrates_only_stopped_profiles(self):
        new=self.lib.prepare_update(self.old.id,self.archive,archive=True)
        self.assertEqual(new.version,"2.0")
        self.assertEqual(new.permissions,("storage","tabs"))
        self.assertEqual(new.host_permissions[-1],"https://new.example/*")
        for pid in self.profile_ids:
            self.assertEqual(self.lib.attached_ids(pid),[self.old.id],
                             "An installed candidate must never auto-attach before review")
        change=self.lib.apply_update(self.old.id,new.id)
        self.assertEqual(change.status,"applied")
        self.assertEqual(set(change.profile_ids),set(self.profile_ids))
        for pid in self.profile_ids:
            self.assertEqual(self.lib.attached_ids(pid),[new.id])
            self.assertEqual(len(self.lib.paths_for(pid)),1)
        self.assertEqual(self.lib.list_upgrades()[0].id,change.id)

    def test_rollback_restores_old_version_and_is_once_only(self):
        new=self.lib.prepare_update(self.old.id,self.archive,archive=True)
        change=self.lib.apply_update(self.old.id,new.id)
        self.assertEqual(self.lib.rollback_update(change.id).status,"rolled_back")
        self.assertEqual(self.lib.list_upgrades()[0].status,"rolled_back")
        for pid in self.profile_ids:
            self.assertEqual(self.lib.attached_ids(pid),[self.old.id])
        with self.assertRaises(ValueError):
            self.lib.rollback_update(change.id)
        # Immutable package records remain available for deliberate re-update.
        self.assertIn(self.old.id,[x.id for x in self.lib.list()])
        self.assertIn(new.id,[x.id for x in self.lib.list()])

    def test_active_profile_blocks_update_without_partial_migration(self):
        new=self.lib.prepare_update(self.old.id,self.archive,archive=True)
        with ProfileLease(self.store.base,self.profile_ids[0]):
            with self.assertRaises(ProfileBusyError):
                self.lib.apply_update(self.old.id,new.id)
        self.assertEqual(self.lib.list_upgrades(),[])
        for pid in self.profile_ids:
            self.assertEqual(self.lib.attached_ids(pid),[self.old.id])

    def test_incompatible_package_rejected_and_cleaned(self):
        self._zip(self.archive,"Another publisher","2.0",[],[])
        with self.assertRaisesRegex(ValueError,"keep its name"):
            self.lib.prepare_update(self.old.id,self.archive,archive=True)
        self.assertEqual([x.id for x in self.lib.list()],[self.old.id])
        self._zip(self.archive,"Demo","1.0",[],[])
        with self.assertRaisesRegex(ValueError,"change its version"):
            self.lib.prepare_update(self.old.id,self.archive,archive=True)
        self.assertEqual(len(self.lib.list()),1)

    def test_manual_changes_refuse_unsafe_rollback(self):
        new=self.lib.prepare_update(self.old.id,self.archive,archive=True)
        change=self.lib.apply_update(self.old.id,new.id)
        self.lib.detach(self.profile_ids[1],new.id)
        with self.assertRaisesRegex(RuntimeError,"manual review"):
            self.lib.rollback_update(change.id)
        # Transaction rollback preserves the other profile's package.
        self.assertEqual(self.lib.attached_ids(self.profile_ids[0]),[new.id])
        self.assertEqual(self.lib.attached_ids(self.profile_ids[1]),[])
        self.assertEqual(self.lib.list_upgrades()[0].status,"applied")

    def test_applied_rollback_record_protects_package_deletion(self):
        new=self.lib.prepare_update(self.old.id,self.archive,archive=True)
        change=self.lib.apply_update(self.old.id,new.id)
        with self.assertRaisesRegex(ValueError,"Rollback"):
            self.lib.remove(self.old.id)
        with self.assertRaisesRegex(ValueError,"Rollback"):
            self.lib.remove(new.id)
        self.lib.rollback_update(change.id)
        self.lib.remove(new.id)
        self.assertEqual([x.id for x in self.lib.list()],[self.old.id])

    def test_prevent_target_already_attached_duplicate(self):
        new=self.lib.prepare_update(self.old.id,self.archive,archive=True)
        self.lib.attach(self.profile_ids[0],new.id)
        with self.assertRaisesRegex(ValueError,"already attached"):
            self.lib.apply_update(self.old.id,new.id)
        self.assertEqual(set(self.lib.attached_ids(self.profile_ids[0])),{self.old.id,new.id})
        self.assertEqual(self.lib.attached_ids(self.profile_ids[1]),[self.old.id])
        self.assertEqual(self.lib.list_upgrades(),[])


if __name__=="__main__":
    unittest.main()
