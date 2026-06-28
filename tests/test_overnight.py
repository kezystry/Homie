"""Overnight — the honest, silent-by-default morning word for the nightly routine.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.gist import Beta, Schema, TimeStat, summarize_fold
from core.overnight import (OvernightDesk, OvernightReport, compose, report_dict,
                            safe_to_disrupt)
from core.ritual import RitualReport
from core.tile import Event


def _firm_schema(tokens, *, daypart="eve", a_q=10000, b_q=0, mass=10000) -> Schema:
    # firmness = bit_length(n_days)-1 ≥ 3 needs n_days ≥ 8 → a_q+b_q ≥ 8000.
    return Schema("rule", "wd", daypart, tuple(tokens), Beta(a_q, b_q),
                  TimeStat(1000, 0, 0), mass)


class SummarizeFoldTests(unittest.TestCase):
    def test_a_newly_firm_line_reads_as_learned(self) -> None:
        prior: list = []
        new = [_firm_schema(("coffee", "kitchen"))]
        s = summarize_fold(prior, new)
        self.assertEqual(s.learned, ("coffee in the kitchen",))
        self.assertTrue(s.changed)

    def test_a_dropped_line_is_forgotten_count_only(self) -> None:
        prior = [_firm_schema(("coffee", "kitchen"))]
        s = summarize_fold(prior, [])
        self.assertEqual(s.forgotten, 1)
        self.assertEqual(s.learned, ())

    def test_a_belief_falling_to_past_tense_is_faded(self) -> None:
        # same line firm in both, confidence high then below the action threshold
        prior = [_firm_schema(("tv", "living"), a_q=10000, b_q=0)]
        new = [_firm_schema(("tv", "living"), a_q=1000, b_q=12000)]   # mostly absence now
        s = summarize_fold(prior, new)
        self.assertEqual(s.faded, ("tv in the living",))
        self.assertEqual(s.forgotten, 0)

    def test_an_unchanged_firm_line_is_kept_not_announced(self) -> None:
        prior = [_firm_schema(("coffee", "kitchen"))]
        new = [_firm_schema(("coffee", "kitchen"))]
        s = summarize_fold(prior, new)
        self.assertFalse(s.changed)
        self.assertEqual(s.kept, 1)


class ComposeTests(unittest.TestCase):
    def test_pure_housekeeping_says_nothing(self) -> None:
        r = RitualReport(at=0.0, compacted=True, decayed=True, gist_folded=42)
        out = compose(r)
        self.assertIsNone(out.spoke)

    def test_a_heal_is_spoken_once_plainly(self) -> None:
        r = RitualReport(at=0.0, healed=["lighting"])
        out = compose(r)
        self.assertEqual(out.spoke, "Overnight I fixed the lighting tile.")

    def test_heal_and_upgrade_merge_into_one_line(self) -> None:
        r = RitualReport(at=0.0, healed=["lighting"])
        out = compose(r, upgrade="applied")
        self.assertEqual(out.spoke, "Overnight I fixed the lighting tile and updated myself.")

    def test_rollback_and_held_are_honest(self) -> None:
        self.assertIn("undid", compose(RitualReport(at=0.0), upgrade="rolledback").spoke)
        self.assertIn("held", compose(RitualReport(at=0.0), upgrade="held").spoke)

    def test_fold_changes_are_detail_only_never_spoken(self) -> None:
        r = RitualReport(at=0.0, gist_folded=3)
        fold = summarize_fold([], [_firm_schema(("coffee", "kitchen"))])
        out = compose(r, fold=fold)
        self.assertIsNone(out.spoke)                       # learning is silent
        self.assertTrue(any("coffee in the kitchen" in d for d in out.detail))


class SafeToDisruptTests(unittest.TestCase):
    def test_no_report_is_not_safe(self) -> None:
        ok, _ = safe_to_disrupt(None)
        self.assertFalse(ok)
        ok, _ = safe_to_disrupt({"present": False})
        self.assertFalse(ok)

    def test_media_live_blocks(self) -> None:
        rep = report_dict(RitualReport(at=1.0), media_live=True)
        ok, why = safe_to_disrupt(rep)
        self.assertFalse(ok)
        self.assertIn("media", why)

    def test_disruptive_abort_blocks(self) -> None:
        r = RitualReport(at=1.0, aborted_disruptive=True, abort_reasons=("home",))
        ok, why = safe_to_disrupt(report_dict(r))
        self.assertFalse(ok)
        self.assertIn("home", why)

    def test_a_clear_quiet_night_is_safe(self) -> None:
        ok, _ = safe_to_disrupt(report_dict(RitualReport(at=1.0)))
        self.assertTrue(ok)


class OvernightDeskTests(unittest.IsolatedAsyncioTestCase):
    async def test_speaks_one_line_on_the_morning_then_stays_quiet(self) -> None:
        bus = Bus()
        says: list = []
        bus.subscribe("interface.say", lambda e: says.append(e.payload["text"]))
        desk = OvernightDesk(bus)
        await desk.start()
        desk.record(compose(RitualReport(at=0.0, healed=["lighting"])), RitualReport(at=0.0))
        await bus.publish(Event("time.morning", 100.0, {"hour": 7}))
        await bus.drain()
        self.assertEqual(says, ["Overnight I fixed the lighting tile."])
        # a second morning with nothing pending stays silent
        await bus.publish(Event("time.morning", 200.0, {"hour": 7}))
        await bus.drain()
        self.assertEqual(len(says), 1)
        await desk.stop(); await bus.aclose()

    async def test_silent_night_speaks_nothing(self) -> None:
        bus = Bus()
        says: list = []
        bus.subscribe("interface.say", lambda e: says.append(e))
        desk = OvernightDesk(bus)
        await desk.start()
        desk.record(compose(RitualReport(at=0.0, gist_folded=9)), RitualReport(at=0.0))
        await bus.publish(Event("time.morning", 100.0, {"hour": 7}))
        await bus.drain()
        self.assertEqual(says, [])
        await desk.stop(); await bus.aclose()

    async def test_writes_the_machine_readable_report_for_the_upgrade(self) -> None:
        with TemporaryDirectory() as d:
            bus = Bus()
            path = Path(d) / "nightly.report"
            desk = OvernightDesk(bus, report_path=path)
            r = RitualReport(at=5.0, healed=["lighting"], restart_decision="soft")
            desk.record(compose(r), r, media_live=True)
            data = json.loads(path.read_text())
            self.assertTrue(data["present"])
            self.assertTrue(data["media_live"])
            self.assertEqual(data["healed"], ["lighting"])
            ok, _ = safe_to_disrupt(data)
            self.assertFalse(ok)                           # media live → not safe to restart
            await bus.aclose()


if __name__ == "__main__":
    unittest.main()
