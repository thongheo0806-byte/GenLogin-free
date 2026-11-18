"""UI independent workflow schema tests and renderable action registry."""
import unittest
from autumn_genlogin.models import validated_steps
from autumn_genlogin.visual_workflow import FIELDS


class VisualWorkflowTests(unittest.TestCase):
    def test_every_visual_action_is_validated_by_engine(self):
        example = {"url": "https://example.com", "selector": "h1", "text": "value", "value": "1", "key": "Enter", "seconds": 0.1}
        for action, keys in FIELDS.items():
            step = {"action": action, **{key: example[key] for key in keys}}
            self.assertEqual(validated_steps([step]), [step])

    def test_no_arbitrary_scripting_action(self):
        for forbidden in ("eval", "execute_script", "shell", "set_cookie", "inject_js"):
            self.assertNotIn(forbidden, FIELDS)


if __name__ == "__main__":
    unittest.main()
