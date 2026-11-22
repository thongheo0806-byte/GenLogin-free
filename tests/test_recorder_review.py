"""Recorder trust boundaries and explicit review requirements."""
import unittest

from autumn_genlogin.recording import (
    MAX_RECORDED_STEPS,
    append_recorded_event,
    review_recording,
    sanitize_recorded_event,
)


class RecordingReviewTests(unittest.TestCase):
    def test_page_cannot_inject_navigation_or_retrieve_sensitive_form_values(self):
        malicious = {"action": "goto", "url": "https://attacker.example/?token=sensitive"}
        self.assertIsNone(sanitize_recorded_event(malicious))
        self.assertIsNone(sanitize_recorded_event({"action": "screenshot"}))
        cleaned = sanitize_recorded_event({
            "action": "fill", "selector": "#input",
            "text": "PRIVATE_LOGIN_SECRET", "sensitive": "PRIVATE_LOGIN_SECRET"
        })
        self.assertEqual(cleaned, {"action":"fill","selector":"#input","text":""})
        self.assertNotIn("PRIVATE_LOGIN_SECRET", repr(cleaned))
        selected = sanitize_recorded_event({
            "action":"select_option", "selector":"#category",
            "value":"PII_PRIVATE"
        })
        self.assertEqual(selected["value"],"REVIEW_OPTION")
        self.assertNotIn("PII_PRIVATE",repr(selected))

    def test_strict_allowed_keys_selectors_and_event_types(self):
        for payload in (None, {}, {"action":"click","selector":""},
                        {"action":"click","selector":"#a\nInjected"},
                        {"action":"click","selector":"x"*241},
                        {"action":"press","selector":"#a","key":"Control+V"},
                        {"action":"extract_text","selector":"body"},
                        {"action":"click_image","template_id":"a"*64,"confidence":0.94}):
            with self.subTest(payload=payload):
                self.assertIsNone(sanitize_recorded_event(payload))
        self.assertEqual(sanitize_recorded_event(
            {"action":"press","selector":"button","key":"Escape"}),
            {"action":"press","selector":"button","key":"Escape"})

    def test_review_shows_all_redactions_and_navigation_without_leaking_urls(self):
        events = [
            {"action":"click","selector":"#start"},
            {"action":"fill","selector":"#secret","text":"PRIVATE"},
            {"action":"select_option","selector":"#chooser","value":"PRIVATE"},
        ]
        result = review_recording(events,navigation_boundaries=3)
        self.assertEqual(result.redacted_fields,2)
        self.assertEqual(result.navigation_boundaries,3)
        self.assertEqual(result.ignored_tabs,0)
        self.assertEqual(result.steps[1]["text"],"")
        self.assertEqual(result.steps[2]["value"],"REVIEW_OPTION")
        summary = result.public_summary()
        self.assertTrue(summary["requires_review"])
        self.assertEqual(summary["step_count"],3)
        self.assertIn("3 page load", " ".join(summary["warnings"]))
        self.assertNotIn("PRIVATE",str(summary))
        self.assertNotIn("PRIVATE",str(result.steps))

    def test_duplicate_form_events_are_compacted_but_double_clicks_survive(self):
        events=[]
        self.assertTrue(append_recorded_event(events,{"action":"fill","selector":"#input","text":"secret1"}))
        self.assertFalse(append_recorded_event(events,{"action":"fill","selector":"#input","text":"secret2"}))
        self.assertTrue(append_recorded_event(events,{"action":"click","selector":"#press"}))
        self.assertTrue(append_recorded_event(events,{"action":"click","selector":"#press"}))
        self.assertEqual([i["action"] for i in events],["fill","click","click"])
        self.assertNotIn("secret",repr(events))

    def test_other_tabs_are_warned_and_invalid_counts_rejected(self):
        result=review_recording(
            [{"action":"press","selector":"#search","key":"Enter"}],
            ignored_tabs=2)
        self.assertEqual(result.public_summary()["ignored_tabs"],2)
        self.assertIn("2 other browser tab", " ".join(result.warnings))
        self.assertNotIn("other browser tab", " ".join(review_recording([]).warnings))
        for bad in (-1,True,1001,"2"):
            with self.subTest(value=bad),self.assertRaises(ValueError):
                review_recording([],ignored_tabs=bad)

    def test_rejects_oversized_and_invalid_legacy_recordings(self):
        with self.assertRaises(ValueError):
            review_recording([{"action":"click","selector":"button"}]*(MAX_RECORDED_STEPS+1))
        with self.assertRaises(ValueError):
            review_recording([{"action":"goto","url":"https://example.com"}])
        with self.assertRaises(ValueError):
            review_recording([],navigation_boundaries=-1)
        self.assertEqual(review_recording([]).steps,[])


if __name__=="__main__":
    unittest.main()
