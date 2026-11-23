"""Strict tab/iframe replay structure and untrusted recorder binding protection."""
from __future__ import annotations

import unittest

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


if __name__=="__main__":
    unittest.main()
