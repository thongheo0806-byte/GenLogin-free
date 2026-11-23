"""Strict tab/iframe replay structure and untrusted recorder binding protection."""
from __future__ import annotations

import unittest
from uuid import uuid4
from types import SimpleNamespace
import asyncio

from autumn_genlogin.browser_shared import SharedBrowserManager
from autumn_genlogin.models import validated_steps
from autumn_genlogin.recording import (
    append_recorded_event, review_recording, sanitize_recorded_event,
)


class TabFrameContextTests(unittest.TestCase):
    def test_page_forged_context_is_stripped_by_default(self):
        forged={"action":"click","selector":"#safe","tab_index":11,
                "tab_count":12,"frames":["#foreign"],"token":"NEVER_LOG"}
        self.assertEqual(sanitize_recorded_event(forged),
                         {"action":"click","selector":"#safe"})
        events=[]
        self.assertTrue(append_recorded_event(
            events, forged, context={"tab_index":1,"tab_count":2,
                                     "frames":["#fixture-frame"]}))
        self.assertEqual(events,[{
            "action":"click","selector":"#safe","tab_index":1,
            "tab_count":2,"frames":["#fixture-frame"]
        }])
        self.assertNotIn("NEVER_LOG",repr(events))

    def test_review_retains_context_and_warns_on_structural_drift(self):
        event={"action":"fill","selector":"#text","text":"secret",
               "tab_index":1,"tab_count":2,"frames":["#frame"]}
        report=review_recording([event])
        self.assertEqual(report.steps,[{
            "action":"fill","selector":"#text","text":"",
            "tab_index":1,"tab_count":2,"frames":["#frame"]
        }])
        self.assertIn("Tab positions",str(report.warnings))
        self.assertIn("Iframe",str(report.warnings))
        self.assertNotIn("secret",str(report.steps))

    def test_invalid_tab_indices_and_frame_paths_fail_closed(self):
        basic={"action":"click","selector":"#safe","tab_index":0,"tab_count":1}
        for patch in ({"tab_index":True},{"tab_index":-1},{"tab_index":1},
                      {"tab_count":0},{"tab_count":13},{"tab_count":True},
                      {"frames":"#frame"},{"frames":["#frame"]*5},
                      {"frames":["#broken" + chr(10) + "name"]},{"frames":[""]}):
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    validated_steps([{**basic,**patch}])
        self.assertEqual(validated_steps([basic])[0],basic)
        with self.assertRaises(ValueError):
            validated_steps([{"action":"goto","url":"http://127.0.0.1:8080",
                              "tab_index":0,"tab_count":1}])


    def test_browser_owned_live_identity_tokens_survive_review_not_forged_payload(self):
        token,frame=str(uuid4()),str(uuid4())
        forged={"action":"click","selector":"#safe",
                "tab_token":str(uuid4()),"frame_tokens":[str(uuid4())]}
        events=[]
        self.assertTrue(append_recorded_event(
            events,forged,context={"tab_index":0,"tab_count":1,
                                  "tab_token":token,
                                  "frames":["#inside"],"frame_tokens":[frame]}))
        self.assertEqual(events,[{
            "action":"click","selector":"#safe",
            "tab_index":0,"tab_count":1,"tab_token":token,
            "frames":["#inside"],"frame_tokens":[frame]
        }])
        self.assertEqual(review_recording(events).steps,events)
        self.assertNotIn(forged["tab_token"],repr(events))

    def test_live_identity_schema_rejects_malformed_and_missing_frame_tokens(self):
        token,frame=str(uuid4()),str(uuid4())
        basic={"action":"click","selector":"#safe",
               "tab_index":0,"tab_count":1,"tab_token":token}
        self.assertEqual(validated_steps([basic])[0],basic)
        frame_step={**basic,"frames":["#inner"],"frame_tokens":[frame]}
        self.assertEqual(validated_steps([frame_step])[0],frame_step)
        for invalid in (
            {**basic,"tab_token":"invalid-token"},
            {**basic,"tab_token":123},
            {**basic,"frames":["#inner"]},
            {**frame_step,"frame_tokens":[]},
            {**frame_step,"frame_tokens":[token,frame]},
            {**frame_step,"frame_tokens":"string"},
            {**frame_step,"frame_tokens":["00000000-0000-0000-0000-000000000000"]},
            {"action":"click","selector":"#safe","tab_token":token},
        ):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                validated_steps([invalid])

    def test_runtime_rejects_replaced_page_with_identical_tab_count(self):
        original=object()
        replacement=object()
        token=str(uuid4())
        state=SimpleNamespace(
            context=SimpleNamespace(pages=[replacement]),
            recorder_tab_tokens={original:token},recorder_frame_tokens={}
        )
        step={"action":"click","selector":"#safe",
              "tab_index":0,"tab_count":1,"tab_token":token}
        async def exercise():
            with self.assertRaisesRegex(RuntimeError,"tab identity changed"):
                await SharedBrowserManager._dom_scope(None,state,step)
            with self.assertRaisesRegex(RuntimeError,"Legacy recording"):
                await SharedBrowserManager._dom_scope(
                    None,state,{k:v for k,v in step.items() if k!="tab_token"})
            state.context.pages=[original]
            self.assertIs(await SharedBrowserManager._dom_scope(None,state,step),
                          original)
        asyncio.run(exercise())


if __name__=="__main__":
    unittest.main()
