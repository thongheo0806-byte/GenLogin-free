"""Frozen pre-refactor workflow contract from main 5b39b8b1.

The legacy validator is copied here only as a differential test oracle.
Production validation must not import this file.
"""
import re
import unittest
from copy import deepcopy
from uuid import UUID

from autumn_genlogin.models import validated_steps, valid_http_url
from autumn_genlogin.recording import ALLOWED_RECORDED_ACTIONS
from autumn_genlogin.visual_workflow import FIELDS

LEGACY_FIELDS = {
    "goto": ("url",),
    "click": ("selector",),
    "click_image": ("template_id", "confidence"),
    "fill": ("selector", "text"),
    "wait": ("seconds",),
    "wait_for": ("selector",),
    "screenshot": (),
    "extract_text": ("selector",),
    "press": ("selector", "key"),
    "check": ("selector",),
    "uncheck": ("selector",),
    "select_option": ("selector", "value"),
    "scroll_into_view": ("selector",),
}
LEGACY_RECORDABLE = frozenset({"click","fill","select_option","check","uncheck","press"})

def legacy_validated_steps(source: object) -> list[dict]:
    """Strict, code-free automation schema; no arbitrary JS/shell execution."""
    if not isinstance(source, list) or not 1 <= len(source) <= 100:
        raise ValueError("Workflow must be a list of 1-100 steps")
    kinds = {
        "goto": ("url",), "click": ("selector",), "click_image": ("template_id", "confidence"), "fill": ("selector", "text"),
        "wait": ("seconds",), "wait_for": ("selector",),
        "screenshot": (), "extract_text": ("selector",),
        "press": ("selector", "key"), "check": ("selector",),
        "uncheck": ("selector",), "select_option": ("selector", "value"),
        "scroll_into_view": ("selector",),
    }
    steps = []
    for number, item in enumerate(source, 1):
        if not isinstance(item, dict) or item.get("action") not in kinds:
            raise ValueError(f"Step {number}: unknown action")
        action = item["action"]
        allowed = {"action", *kinds[action]}
        # Recorded DOM actions can target a precise tab slot and nested frame.
        # Legacy steps without this context still target the first tab.
        if any(key in item for key in (
                "tab_index", "tab_count", "frames", "tab_token", "frame_tokens")):
            if "selector" not in kinds[action]:
                raise ValueError(f"Step {number}: tab/frame context requires a DOM selector")
            allowed.update({"tab_index", "tab_count"})
            for optional in ("frames", "tab_token", "frame_tokens"):
                if optional in item:
                    allowed.add(optional)
        if set(item) != allowed:
            raise ValueError(f"Step {number}: unexpected or missing fields")
        for key in kinds[action]:
            value = item[key]
            if key in {"seconds", "confidence"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"Step {number}: {key} must be numeric")
                if key == "seconds" and not 0 <= value <= 30:
                    raise ValueError(f"Step {number}: wait must be 0-30 seconds")
                if key == "confidence" and not 0.90 <= value <= 1:
                    raise ValueError(f"Step {number}: image confidence must be 0.90-1.00")
            elif not isinstance(value, str) or (not value and key != "text") or len(value) > 4096:
                raise ValueError(f"Step {number}: invalid {key}")
        if "tab_index" in item:
            tab, count = item["tab_index"], item["tab_count"]
            if (type(tab) is not int or type(count) is not int
                    or not 1 <= count <= 12 or not 0 <= tab < count):
                raise ValueError(f"Step {number}: invalid tab position or count")
            frames = item.get("frames", [])
            if (not isinstance(frames, list) or len(frames) > 4
                    or any(not isinstance(sel, str) or not sel or len(sel) > 240
                           or any(ord(ch) < 32 or ord(ch) == 127 for ch in sel)
                           for sel in frames)):
                raise ValueError(f"Step {number}: invalid iframe selector path")
            if "tab_token" in item:
                token=item["tab_token"]
                if (not isinstance(token,str) or
                        not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",token)):
                    raise ValueError(f"Step {number}: invalid live tab identity token")
                from uuid import UUID
                if UUID(token).version!=4:
                    raise ValueError(f"Step {number}: invalid live tab identity token")
                if frames and "frame_tokens" not in item:
                    raise ValueError(f"Step {number}: missing live iframe identities")
            if "frame_tokens" in item:
                tokens=item["frame_tokens"]
                if ("tab_token" not in item or not frames or
                        not isinstance(tokens,list) or len(tokens)!=len(frames)
                        or any(not isinstance(token,str) or
                               not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",token)
                               for token in tokens)):
                    raise ValueError(f"Step {number}: invalid live iframe identities")
                from uuid import UUID
                if any(UUID(token).version!=4 for token in tokens):
                    raise ValueError(f"Step {number}: invalid live iframe identities")
        if action == "goto":
            valid_http_url(item["url"])
        if action == "click_image" and not re.fullmatch(r"[0-9a-f]{64}", item["template_id"]):
            raise ValueError(f"Step {number}: invalid image template ID")
        if "selector" in item and any(c in item["selector"] for c in "\x00\r\n"):
            raise ValueError(f"Step {number}: invalid selector")
        steps.append(item.copy())
    return steps


class ActionSchemaEquivalenceTests(unittest.TestCase):
    def test_editor_fields_and_recordable_actions_remain_identical(self):
        self.assertEqual(FIELDS, LEGACY_FIELDS)
        self.assertEqual(tuple(FIELDS), tuple(LEGACY_FIELDS))
        self.assertEqual(ALLOWED_RECORDED_ACTIONS, LEGACY_RECORDABLE)

    def test_differential_valid_and_invalid_action_inputs(self):
        values = {"url":"https://example.com", "selector":"#fixture",
                  "template_id":"a"*64, "confidence":0.94, "seconds":1,
                  "text":"", "key":"Enter", "value":"example"}
        cases = [None, {}, [], [{}], [None], [{"action":"execute_script"}]]
        token="01234567-89ab-4def-8123-456789abcdef"
        for action,fields in LEGACY_FIELDS.items():
            valid={"action":action, **{field:values[field] for field in fields}}
            cases.append([valid])
            cases.append([{**valid,"unexpected":"fixture"}])
            for key in fields:
                missing=deepcopy(valid)
                del missing[key]
                cases.append([missing])
                for value in (None,True,False,0,-1,31,0.89,1.01,float("nan"),
                              "", "x"*4097, [], {}, "a\x00b", "a\nb"):
                    cases.append([{**valid,key:value}])
            for context in (
                {"tab_index":0,"tab_count":1},
                {"tab_index":1,"tab_count":1},
                {"tab_index":False,"tab_count":1},
                {"frames":["#frame"]},
                {"tab_index":0,"tab_count":2,"frames":["#frame"]},
                {"tab_index":0,"tab_count":1,"frames":["#frame"],"tab_token":token},
                {"tab_index":0,"tab_count":1,"frames":["#frame"],"tab_token":token,"frame_tokens":[token]},
                {"tab_index":0,"tab_count":1,"tab_token":"invalid"},
                {"tab_index":0,"tab_count":1,"frames":["a\nb"]},
            ):
                cases.append([{**valid,**context}])
        cases.extend([[{"action":"goto","url":url}] for url in
                      ("file:///private","javascript:alert(1)","https://name:pass@example.com","https://example.com")])
        cases.append([{"action":"wait","seconds":0}]*100)
        cases.append([{"action":"wait","seconds":0}]*101)
        def outcome(fn,case):
            try:
                return ("ok",fn(deepcopy(case)))
            except (TypeError,ValueError) as exc:
                return (type(exc).__name__,str(exc))
        for number,case in enumerate(cases):
            with self.subTest(case=number):
                self.assertEqual(outcome(validated_steps,case),
                                 outcome(legacy_validated_steps,case))


if __name__=="__main__":
    unittest.main()
