import unittest
from autumn_genlogin.models import validated_steps

class WorkflowEnhancementTests(unittest.TestCase):
    def test_new_safe_actions(self):
        steps = validated_steps([
            {"action": "press", "selector": "#search", "key": "Enter"},
            {"action": "check", "selector": "#terms"},
            {"action": "uncheck", "selector": "#terms"},
            {"action": "select_option", "selector": "select", "value": "1"},
            {"action": "scroll_into_view", "selector": "footer"}
        ])
        self.assertEqual(len(steps), 5)

    def test_rejects_unsupported_action(self):
        with self.assertRaises(ValueError):
            validated_steps([{"action": "eval", "code": "alert(1)"}])

    def test_rejects_control_characters_in_selector(self):
        with self.assertRaises(ValueError):
            validated_steps([{"action": "check", "selector": "#a\n"}])
