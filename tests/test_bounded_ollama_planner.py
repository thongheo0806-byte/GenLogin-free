"""The bounded planner can choose only an enumerated synthetic action."""
import unittest
from experiments.browser_use_lab.bounded_planner import parse_choice


class BoundedPlannerTests(unittest.TestCase):
    def test_strict_enum_json(self):
        self.assertEqual(parse_choice('{"choice":"option-2"}',("option-1","option-2")),
                         "option-2")

    def test_rejects_model_code_unknown_choice_and_ambiguous_object(self):
        invalid=(
            '{"choice":"option-3"}',
            '{"choice":"option-1","url":"https://example.org"}',
            '{"choice":"option-1","choice":"option-2"}',
            '{"choice":1}',
            '["option-1"]',
            '{"choice":"#password"}',
            'TEST-OK',
            '{"choice":"option-1"}; print("bad")',
            " " * 257,
        )
        for output in invalid:
            with self.subTest(output=output), self.assertRaises(ValueError):
                parse_choice(output,("option-1","option-2"))


if __name__=="__main__":
    unittest.main()
