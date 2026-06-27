"""The status page — gathered from real sources, renders without a daemon, and never
crashes on a missing state dir. (The page is observability; these guard its plumbing.)

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core import status as S

ROOT = Path(__file__).resolve().parents[1]

SAMPLE = """# Homie — Progress

## At a glance

```
M0   ✅ shipped   Pi-anchor chat fallback
M2.5 ✅ shipped   The clock
M5   🔄 building   Capability-gated act path
M6   ⏳ planned    8B serving discipline
```

## Now / Next
text after the block — must be ignored.
M9 ⏳ planned should NOT be parsed (outside the fence)
"""


class ParseTests(unittest.TestCase):
    def test_parses_glance_block_only(self) -> None:
        ms = S.parse_milestones(SAMPLE)
        self.assertEqual([m.id for m in ms], ["M0", "M2.5", "M5", "M6"])  # M9 outside the fence excluded
        by = {m.id: m for m in ms}
        self.assertEqual(by["M0"].status, "shipped")
        self.assertEqual(by["M5"].status, "building")
        self.assertEqual(by["M6"].status, "planned")
        self.assertEqual(by["M0"].icon, "✅")
        self.assertEqual(by["M5"].css, "wip")
        self.assertIn("Capability", by["M5"].text)

    def test_real_progress_file_parses_and_has_shipped(self) -> None:
        prog = (ROOT / "docs" / "PROGRESS.md").read_text("utf-8")
        ms = S.parse_milestones(prog)
        self.assertTrue(any(m.id == "M0" for m in ms))
        self.assertTrue(any(m.status == "shipped" for m in ms))


class RuntimeFactsTests(unittest.TestCase):
    def test_missing_state_is_graceful(self) -> None:
        self.assertEqual(S.runtime_facts(None)["present"], False)
        self.assertEqual(S.runtime_facts(Path("/no/such/dir/xyz"))["present"], False)

    def test_reads_events_and_lessons(self) -> None:
        with TemporaryDirectory() as d:
            state = Path(d)
            (state / "events.jsonl").write_text('{"a":1}\n{"a":2}\n', "utf-8")
            ls = state / "tiles" / "lighting" / "state"
            ls.mkdir(parents=True)
            (ls / "data.json").write_text(json.dumps({"suppressed": {"kitchen": [19], "den": [7, 23]}}), "utf-8")
            rt = S.runtime_facts(state)
            self.assertTrue(rt["present"])
            self.assertEqual(rt["events"]["count"], 2)
            self.assertIsNotNone(rt["events"]["last_activity"])
            rooms = {(l["room"], tuple(l["hours"])) for l in rt["lessons"]}
            self.assertEqual(rooms, {("kitchen", (19,)), ("den", (7, 23))})


class RenderTests(unittest.TestCase):
    def _facts(self, **over):
        base = {
            "generated_at": "2026-06-27 12:00:00 UTC",
            "milestones": S.parse_milestones(SAMPLE),
            "shipped": 2, "total": 4,
            "git": {"branch": "claude/homie-overview-bo4l8v",
                    "commits": [{"hash": "abc1234", "subject": "M4: spoken lesson"}]},
            "tests": {"ran": None, "skipped": True},
            "runtime": {"present": False, "reason": "no state directory configured"},
        }
        base.update(over)
        return base

    def test_render_is_self_contained_html(self) -> None:
        out = S.render_html(self._facts(), live=False)
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertIn("Homie", out)
        self.assertIn("claude/homie-overview-bo4l8v", out)
        self.assertIn("M5", out)
        self.assertIn("abc1234", out)
        self.assertNotIn("http://", out.split("<style>")[0])  # no external asset links in head
        self.assertNotIn("<meta http-equiv=\"refresh\"", out)  # snapshot mode has no refresh

    def test_live_mode_adds_refresh(self) -> None:
        out = S.render_html(self._facts(), live=True, refresh=7)
        self.assertIn('http-equiv="refresh" content="7"', out)

    def test_tests_pill_reflects_result(self) -> None:
        ok = S.render_html(self._facts(tests={"ran": True, "ok": True, "count": 271, "duration": 1.7}))
        self.assertIn("271 passing", ok)
        bad = S.render_html(self._facts(tests={"ran": True, "ok": False, "count": 270, "duration": 1.9}))
        self.assertIn("FAILING", bad)

    def test_lessons_render_when_present(self) -> None:
        facts = self._facts(runtime={"present": True, "path": "/var/lib/homie",
                                     "events": {"count": 42, "last_activity": "2026-06-27T10:00:00+00:00"},
                                     "lessons": [{"tile": "lighting", "room": "kitchen", "hours": [19]}]})
        out = S.render_html(facts)
        self.assertIn("kitchen", out)
        self.assertIn("7pm", out)
        self.assertIn("42", out)


class GatherTests(unittest.TestCase):
    def test_gather_without_tests_is_offline_safe(self) -> None:
        facts = S.gather(run_tests=False)
        self.assertIn("milestones", facts)
        self.assertEqual(facts["tests"].get("skipped"), True)
        self.assertIn("branch", facts["git"])
        # renders end-to-end from a real gather
        self.assertTrue(S.render_html(facts).startswith("<!DOCTYPE html>"))


if __name__ == "__main__":
    unittest.main()
