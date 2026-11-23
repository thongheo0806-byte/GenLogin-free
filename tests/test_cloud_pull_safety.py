"""Fail-closed TeamHub pull reconciliation and atomic local snapshot checks.

All fixtures use synthetic profile metadata and a local SQLite database.
No remote accounts or credentials are required.
"""
from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from autumn_genlogin.cloud_merge import prepare_cloud_profile_pull
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store
from autumn_genlogin.team_sync import merge_safe_profiles, safe_profile_metadata


class CloudPullSafetyTests(unittest.TestCase):
    def setUp(self):
        self.home=tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.store=Store(Path(self.home.name)/"local")
        self.profile=self.store.save(Profile(name="Local original",tags="local"))
        self.baseline=safe_profile_metadata(self.store)

    def test_first_pull_combines_disjoint_profiles_without_deleting_local(self):
        second=Profile(name="Remote-only",group_name="Shared")
        remote=deepcopy(self.baseline)
        remote["profiles"]=[{
            **remote["profiles"][0],
            "id":second.id,"name":second.name,"group_name":second.group_name,
        }]
        merged,conflicts=prepare_cloud_profile_pull(self.baseline,remote)
        self.assertEqual(conflicts,())
        self.assertEqual({r["id"] for r in merged["profiles"]},
                         {self.profile.id,second.id})
        self.assertEqual(self.store.get(self.profile.id).name,"Local original")
        expected=deepcopy(self.baseline)
        merged_records=[r for r in merged["profiles"]
                        if r["id"] not in {x["id"] for x in expected["profiles"]}]
        changed=merge_safe_profiles(
            self.store,{"format":merged["format"],"profiles":merged_records},
            expected_local=expected)
        self.assertEqual(changed,1)
        self.assertEqual(self.store.get(second.id).name,"Remote-only")
        self.assertEqual(self.store.get(self.profile.id).name,"Local original")

    def test_first_pull_rejects_same_id_conflict_and_keeps_local_untouched(self):
        remote=deepcopy(self.baseline)
        remote["profiles"][0]["name"]="REMOTE_WOULD_CLOBBER"
        merged,conflicts=prepare_cloud_profile_pull(self.baseline,remote)
        self.assertIsNone(merged)
        self.assertEqual(conflicts,(self.profile.id+":unverified-overlap",))
        self.assertEqual(self.store.get(self.profile.id).name,"Local original")
        self.assertNotIn("REMOTE_WOULD_CLOBBER",str(conflicts))

    def test_first_pull_accepts_identical_existing_profile(self):
        merged,conflicts=prepare_cloud_profile_pull(self.baseline,self.baseline)
        self.assertEqual(conflicts,())
        self.assertEqual(merged["profiles"],self.baseline["profiles"])

    def test_known_baseline_merges_nonoverlapping_fields(self):
        local=deepcopy(self.baseline)
        remote=deepcopy(self.baseline)
        local["profiles"][0]["name"]="Local new name"
        remote["profiles"][0]["tags"]="Remote new tag"
        merged,conflicts=prepare_cloud_profile_pull(local,remote,self.baseline)
        self.assertEqual(conflicts,())
        self.assertEqual(merged["profiles"][0]["name"],"Local new name")
        self.assertEqual(merged["profiles"][0]["tags"],"Remote new tag")
        remote["profiles"][0]["name"]="Remote divergent name"
        merged,conflicts=prepare_cloud_profile_pull(local,remote,self.baseline)
        self.assertIsNone(merged)
        self.assertEqual(conflicts,(self.profile.id+":name",))

    def test_preview_stale_after_local_edit_is_rejected_atomically(self):
        expected=safe_profile_metadata(self.store)
        remote=deepcopy(expected)
        remote["profiles"][0]["name"]="Proposed remote name"
        self.store.save(Profile(**{
            **self.profile.public_dict(),"name":"Changed in another UI",
        }))
        with self.assertRaisesRegex(ValueError,"changed since cloud preview"):
            merge_safe_profiles(self.store,remote,expected_local=expected)
        self.assertEqual(self.store.get(self.profile.id).name,"Changed in another UI")

    def test_multiple_profiles_apply_or_rollback_as_one_transaction(self):
        extra=Profile(name="Extra")
        self.store.save(extra)
        expected=safe_profile_metadata(self.store)
        proposed=deepcopy(expected)
        proposed["profiles"][0]["name"]="Update one"
        proposed["profiles"][1]["name"]=""
        # Invalid profile must not partially update any previous valid row.
        with self.assertRaises(ValueError):
            merge_safe_profiles(self.store,proposed,expected_local=expected)
        self.assertEqual(safe_profile_metadata(self.store),expected)

    def test_preview_rejection_when_profile_open_does_not_modify_store(self):
        expected=safe_profile_metadata(self.store)
        remote=deepcopy(expected)
        remote["profiles"][0]["tags"]="Remote modification"
        with self.assertRaisesRegex(ValueError,"Stop running profiles"):
            merge_safe_profiles(
                self.store,remote,expected_local=expected,
                active=lambda pid:pid==self.profile.id)
        self.assertEqual(safe_profile_metadata(self.store),expected)


if __name__=="__main__":
    unittest.main()
