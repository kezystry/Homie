"""Reason.validate_tool_call — the structural gate on model tool calls.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.reason import validate_tool_call

CATALOG = [
    {"type": "function", "function": {"name": "agenda", "parameters": {"type": "object", "properties": {}}}},
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "priority": {"type": "integer"}},
                "required": ["text"],
            },
        },
    },
]


class ValidateToolCallTests(unittest.TestCase):
    def test_valid_call_no_errors(self) -> None:
        self.assertEqual(validate_tool_call(CATALOG, "add_reminder", {"text": "dentist"}), [])

    def test_no_param_function(self) -> None:
        self.assertEqual(validate_tool_call(CATALOG, "agenda", {}), [])

    def test_unknown_function_rejected(self) -> None:
        errs = validate_tool_call(CATALOG, "launch_missiles", {})
        self.assertEqual(len(errs), 1)
        self.assertIn("unknown function", errs[0])

    def test_missing_required_arg(self) -> None:
        errs = validate_tool_call(CATALOG, "add_reminder", {})
        self.assertTrue(any("missing required arg 'text'" in e for e in errs))

    def test_unexpected_arg_rejected(self) -> None:
        errs = validate_tool_call(CATALOG, "add_reminder", {"text": "x", "ctx": "sneaky"})
        self.assertTrue(any("unexpected arg 'ctx'" in e for e in errs))

    def test_type_mismatch(self) -> None:
        errs = validate_tool_call(CATALOG, "add_reminder", {"text": 123})
        self.assertTrue(any("must be string" in e for e in errs))

    def test_integer_not_bool(self) -> None:
        # a bool must not satisfy integer (Python bool is an int subclass)
        errs = validate_tool_call(CATALOG, "add_reminder", {"text": "x", "priority": True})
        self.assertTrue(any("priority" in e for e in errs))
        self.assertEqual(validate_tool_call(CATALOG, "add_reminder", {"text": "x", "priority": 2}), [])


if __name__ == "__main__":
    unittest.main()
