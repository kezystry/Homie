"""Self-update decision logic — conservative: anything uncertain is 'not safe'.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core import selfupdate


class ParsePullTests(unittest.TestCase):
    def test_failed_pull(self) -> None:
        r = selfupdate.parse_pull(1, "", "fatal: not a git repository", "a" * 40, "a" * 40)
        self.assertFalse(r["ok"])
        self.assertFalse(r["changed"])
        self.assertIn("not a git repository", r["summary"])

    def test_no_change(self) -> None:
        r = selfupdate.parse_pull(0, "Already up to date.\n", "", "abc123", "abc123")
        self.assertTrue(r["ok"])
        self.assertFalse(r["changed"])

    def test_changed(self) -> None:
        r = selfupdate.parse_pull(0, "Updating...\n", "", "abc1234ff", "def5678aa")
        self.assertTrue(r["ok"])
        self.assertTrue(r["changed"])
        self.assertIn("abc1234", r["summary"])
        self.assertIn("def5678", r["summary"])


class DecideTests(unittest.TestCase):
    def test_pull_failure_is_unsafe(self) -> None:
        safe, msg = selfupdate.decide({"ok": False, "summary": "boom"}, {"ran": None})
        self.assertFalse(safe)
        self.assertIn("untouched", msg)

    def test_no_change_is_safe_no_restart(self) -> None:
        safe, msg = selfupdate.decide({"ok": True, "changed": False}, {"ran": None})
        self.assertTrue(safe)
        self.assertIn("up to date", msg)

    def test_changed_but_tests_didnt_run_is_unsafe(self) -> None:
        safe, msg = selfupdate.decide({"ok": True, "changed": True}, {"ran": None})
        self.assertFalse(safe)
        self.assertIn("not safe", msg.lower())

    def test_changed_and_green_is_safe(self) -> None:
        safe, msg = selfupdate.decide({"ok": True, "changed": True}, {"ran": True, "ok": True, "count": 297})
        self.assertTrue(safe)
        self.assertIn("297", msg)

    def test_changed_and_red_is_unsafe_with_rollback_hint(self) -> None:
        safe, msg = selfupdate.decide({"ok": True, "changed": True}, {"ran": True, "ok": False, "count": 297})
        self.assertFalse(safe)
        self.assertIn("reset --hard", msg)


class FormatTests(unittest.TestCase):
    def test_report_mentions_restart_path_when_safe_and_changed(self) -> None:
        out = selfupdate.format_report({"ok": True, "changed": True, "summary": "updated a → b"},
                                       {"ran": True, "ok": True, "count": 297, "duration": 1.7},
                                       True, "healthy", restarted=False)
        self.assertIn("systemctl restart homie", out)
        self.assertIn("297 passed", out)

    def test_report_notes_a_restart(self) -> None:
        out = selfupdate.format_report({"ok": True, "changed": True, "summary": "x"},
                                       {"ran": True, "ok": True, "count": 1, "duration": 0.1},
                                       True, "healthy", restarted=True)
        self.assertIn("restarted", out)


if __name__ == "__main__":
    unittest.main()
