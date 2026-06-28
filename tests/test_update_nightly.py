"""The nightly self-upgrade gate — defer if a film is playing or the home was active.

Run: python3 -m unittest discover -s tests
"""
import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "update.py"
_spec = importlib.util.spec_from_file_location("homie_update", _PATH)
update = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update)


class RestartGateTests(unittest.TestCase):
    def test_clear_when_nothing_is_happening(self) -> None:
        with TemporaryDirectory() as d:
            ok, _ = update._restart_gate(Path(d))
            self.assertTrue(ok)

    def test_defers_while_a_film_is_playing(self) -> None:
        with TemporaryDirectory() as d:
            (Path(d) / "now.json").write_text('{"title":"X"}')
            ok, why = update._restart_gate(Path(d))
            self.assertFalse(ok)
            self.assertIn("playing", why)

    def test_defers_when_the_home_was_active_overnight(self) -> None:
        with TemporaryDirectory() as d:
            (Path(d) / "nightly.report").write_text(json.dumps(
                {"present": True, "aborted_disruptive": True, "abort_reasons": ["home"]}))
            ok, why = update._restart_gate(Path(d))
            self.assertFalse(ok)
            self.assertIn("home", why)

    def test_a_quiet_report_does_not_defer(self) -> None:
        with TemporaryDirectory() as d:
            (Path(d) / "nightly.report").write_text(json.dumps(
                {"present": True, "aborted_disruptive": False, "abort_reasons": []}))
            ok, _ = update._restart_gate(Path(d))
            self.assertTrue(ok)


class WriteOutcomeTests(unittest.TestCase):
    def test_writes_the_status_for_the_morning_word(self) -> None:
        with TemporaryDirectory() as d:
            update._write_outcome(Path(d), "applied")
            data = json.loads((Path(d) / "upgrade.outcome").read_text())
            self.assertEqual(data["status"], "applied")

    def test_none_writes_nothing(self) -> None:
        with TemporaryDirectory() as d:
            update._write_outcome(Path(d), None)
            self.assertFalse((Path(d) / "upgrade.outcome").exists())


if __name__ == "__main__":
    unittest.main()
