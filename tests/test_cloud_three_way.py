"""Three-way encrypted metadata merge, fail-closed conflicts and real CAS HTTP."""
from __future__ import annotations

from copy import deepcopy
import tempfile
import threading
import unittest
from pathlib import Path

from autumn_genlogin.cloud_merge import merge_cloud_documents
from autumn_genlogin.models import Profile
from autumn_genlogin.team_sync import (
    CloudClient, HubError, HubHTTPServer, TeamHub, safe_profile_metadata,
)
from autumn_genlogin.storage import Store


class MetadataMergeTests(unittest.TestCase):
    def setUp(self):
        self.home=tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.store=Store(Path(self.home.name)/"profiles")
        self.profile=self.store.save(Profile(name="Synthetic starting name",tags="A"))
        self.base=safe_profile_metadata(self.store)

    def copy(self):
        return deepcopy(self.base)

    def test_nonoverlapping_changes_are_reconciled(self):
        local,remote=self.copy(),self.copy()
        local["profiles"][0]["name"]="Local rename"
        remote["profiles"][0]["tags"]="Remote tag"
        merged,conflicts=merge_cloud_documents("profiles",self.base,local,remote)
        self.assertEqual(conflicts,())
        self.assertEqual(merged["profiles"][0]["name"],"Local rename")
        self.assertEqual(merged["profiles"][0]["tags"],"Remote tag")
        self.assertEqual(self.base["profiles"][0]["name"],"Synthetic starting name")

    def test_overlapping_field_changes_report_only_field_names(self):
        local,remote=self.copy(),self.copy()
        local["profiles"][0]["name"]="LOCAL_SECRET"
        remote["profiles"][0]["name"]="REMOTE_SECRET"
        merged,conflicts=merge_cloud_documents("profiles",self.base,local,remote)
        self.assertIsNone(merged)
        self.assertEqual(conflicts,(self.profile.id+":name",))
        self.assertNotIn("SECRET",repr(conflicts))

    def test_unknown_baseline_never_clobbers_existing_remote(self):
        local=self.copy()
        remote=self.copy()
        remote["profiles"][0]["tags"]="remote"
        result,conflicts=merge_cloud_documents("profiles",None,local,remote)
        self.assertIsNone(result)
        self.assertEqual(conflicts,("no-shared-baseline",))
        empty_result,empty_conflicts=merge_cloud_documents(
            "profiles",None,local,None)
        self.assertEqual(empty_result,local)
        self.assertEqual(empty_conflicts,())

    def test_deletion_is_not_inferred_and_extra_fields_rejected(self):
        local,remote=self.copy(),self.copy()
        local["profiles"]=[]
        remote["profiles"]=[]
        merged,conflicts=merge_cloud_documents("profiles",self.base,local,remote)
        self.assertEqual(conflicts,())
        self.assertEqual(merged["profiles"][0]["id"],self.profile.id)
        remote=self.copy()
        remote["profiles"][0]["proxy_username"]="SHOULD_NOT_SYNC"
        with self.assertRaises(ValueError):
            merge_cloud_documents("profiles",self.base,self.base,remote)

    def test_workflow_divergence_is_never_auto_merged(self):
        base={"format":"AutumnGenLogin/workflow-1",
              "workflow":[{"action":"click","selector":"#original"}]}
        local=deepcopy(base)
        remote=deepcopy(base)
        local["workflow"][0]["selector"]="#local"
        remote["workflow"][0]["selector"]="#remote"
        result,conflicts=merge_cloud_documents("workflows",base,local,remote)
        self.assertIsNone(result)
        self.assertEqual(conflicts,("workflow-diverged",))
        result,conflicts=merge_cloud_documents("workflows",base,local,base)
        self.assertEqual(result,local)


class HTTPRevisionCASTests(unittest.TestCase):
    def test_concurrent_team_metadata_update_rejects_stale_revision(self):
        with tempfile.TemporaryDirectory() as home:
            hub=TeamHub(Path(home)/"hub.sqlite")
            server=HubHTTPServer(("127.0.0.1",0),hub)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                url=f"http://127.0.0.1:{server.server_port}"
                a,b=CloudClient(url),CloudClient(url)
                a.register("editorA","password_for_test_editorA")
                b.register("editorB","password_for_test_editorB")
                a.login("editorA","password_for_test_editorA")
                b.login("editorB","password_for_test_editorB")
                team=a.create_team("Conflict fixture")
                a.set_member(team,"editorB","editor")
                key="synthetic shared team password"
                doc={"format":"AutumnGenLogin/profile-metadata-1","profiles":[]}
                self.assertEqual(a.push(team,"profiles",0,doc,key),1)
                rev_a,_=a.pull(team,"profiles",key)
                rev_b,_=b.pull(team,"profiles",key)
                self.assertEqual(rev_a,rev_b)
                self.assertEqual(a.push(team,"profiles",rev_a,doc,key),2)
                with self.assertRaises(HubError) as failure:
                    b.push(team,"profiles",rev_b,doc,key)
                self.assertEqual(failure.exception.status,409)
                self.assertEqual(b.pull(team,"profiles",key)[0],2)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())


if __name__=="__main__":
    unittest.main()
