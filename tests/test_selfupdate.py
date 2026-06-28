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

    def test_changed_and_red_is_unsafe_and_rolls_back(self) -> None:
        pull, tests = {"ok": True, "changed": True}, {"ran": True, "ok": False, "count": 297}
        safe, msg = selfupdate.decide(pull, tests)
        self.assertFalse(safe)
        self.assertIn("rolling back", msg.lower())
        self.assertTrue(selfupdate.should_rollback(pull, tests))


class AuthorityGuardTests(unittest.TestCase):
    def test_authority_touched_flags_sensitive_paths(self) -> None:
        touched = selfupdate.authority_touched(
            ["core/voice.py", "deploy/act_map.toml", "tiles/desktop/handlers.py", "core/capability.py"])
        self.assertIn("deploy/act_map.toml", touched)
        self.assertIn("core/capability.py", touched)
        self.assertNotIn("core/voice.py", touched)            # ordinary code is fine

    def test_green_but_authority_change_is_held_not_applied(self) -> None:
        safe, msg = selfupdate.decide(
            {"ok": True, "changed": True}, {"ran": True, "ok": True, "count": 600},
            changed_files=["core/capability.py"])
        self.assertFalse(safe)                                 # green, yet NOT auto-applied
        self.assertIn("explicit yes", msg)
        # an authority hold is NOT a rollback — the code is healthy, it just waits for the owner
        self.assertFalse(selfupdate.should_rollback(
            {"ok": True, "changed": True}, {"ran": True, "ok": True, "count": 600},
            ["core/capability.py"]))

    def test_green_ordinary_change_applies(self) -> None:
        safe, _ = selfupdate.decide(
            {"ok": True, "changed": True}, {"ran": True, "ok": True, "count": 600},
            changed_files=["core/journal.py", "docs/PROGRESS.md"])
        self.assertTrue(safe)


class ChangelogTests(unittest.TestCase):
    def test_changelog_line_records_the_verdict(self) -> None:
        applied = selfupdate.changelog_line(
            {"ok": True, "changed": True, "summary": "a → b"},
            {"ran": True, "ok": True, "count": 600}, True, "healthy", when="2026-06-29")
        self.assertIn("applied", applied)
        rolled = selfupdate.changelog_line(
            {"ok": True, "changed": True, "summary": "a → c"},
            {"ran": True, "ok": False, "count": 600}, False, "failed", when="2026-06-29")
        self.assertIn("rolled-back", rolled)


class UpgradeOutcomeTests(unittest.TestCase):
    _GREEN = {"ran": True, "ok": True, "count": 300, "duration": 1.0}
    _CHANGED = {"ok": True, "changed": True, "summary": "a → b"}

    def test_nothing_to_say_when_unchanged(self) -> None:
        self.assertIsNone(selfupdate.upgrade_outcome({"ok": True, "changed": False},
                                                     {"ran": None}, [], restarted=False))

    def test_applied_when_restarted(self) -> None:
        self.assertEqual(selfupdate.upgrade_outcome(self._CHANGED, self._GREEN, ["core/x.py"],
                                                    restarted=True), "applied")

    def test_rolledback_when_tests_failed(self) -> None:
        self.assertEqual(selfupdate.upgrade_outcome(self._CHANGED, {"ran": True, "ok": False, "count": 3},
                                                    ["core/x.py"], restarted=False), "rolledback")

    def test_held_when_authority_touched_but_green(self) -> None:
        self.assertEqual(selfupdate.upgrade_outcome(self._CHANGED, self._GREEN,
                                                    ["core/capability.py"], restarted=False), "held")


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
