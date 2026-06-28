"""Phase B — honest beliefs. The probability a belief surface may state must be a real
probability: in [0,1], mean-reverting when a routine stops, and silent below the evidence
floor. These tests FAIL on the pre-Phase-B model (where count/days could exceed 1.0).

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timedelta, timezone

from core.remember import NMIN_DAYS, PatternModel
from core.tile import Event

_BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def ev(topic: str, dt: datetime, zone: str | None = "kitchen") -> Event:
    return Event(topic, dt.timestamp(), {"zone": zone}, source="test")


def day(d: int, hour: int = 8) -> datetime:
    # Day d (1-based) at `hour`, in fixed UTC so hour-buckets are stable across CI hosts.
    return _BASE + timedelta(days=d - 1, hours=hour)


class ProbabilityIsBounded(unittest.TestCase):
    def test_multiple_events_per_day_never_exceed_one(self) -> None:
        # The live bug: firing the same routine 3x/day made count/days = 3.0. prob must stay 1.0.
        m = PatternModel(tz="UTC")
        for d in range(1, 11):                      # ten days, three fires each at 08:00
            for _ in range(3):
                m.observe(ev("presence.arrived", day(d, 8)))
        exp = m.expectation("presence.arrived", "kitchen", day(10, 8).timestamp())
        self.assertLessEqual(exp.prob, 1.0)
        self.assertGreater(exp.prob, 0.9)           # present essentially every day at 08:00
        self.assertGreater(exp.rate, 1.0)           # rate (events/day) is still ~3, unchanged

    def test_half_the_days_reads_about_half(self) -> None:
        m = PatternModel(tz="UTC")
        for d in range(1, 21):                       # 20 active days...
            m.observe(ev("motion.detected", day(d, 7)))      # the home is active every day
            if d % 2 == 0:                                   # ...but THIS routine fires every 2nd
                m.observe(ev("presence.arrived", day(d, 9)))
        exp = m.expectation("presence.arrived", "kitchen", day(20, 9).timestamp())
        self.assertGreater(exp.prob, 0.35)
        self.assertLess(exp.prob, 0.65)              # ~0.5, a real probability on the global denom


class StoppedRoutineMeanReverts(unittest.TestCase):
    def test_prob_falls_after_the_routine_stops(self) -> None:
        m = PatternModel(tz="UTC")
        for d in range(1, 21):                       # 20 solid days of a 09:00 routine
            m.observe(ev("presence.arrived", day(d, 9)))
        before = m.expectation("presence.arrived", "kitchen", day(20, 9).timestamp()).prob
        # The routine stops, but the HOME stays active (other perception) for 20 more days.
        for d in range(21, 41):
            m.observe(ev("motion.detected", day(d, 7)))
        after = m.expectation("presence.arrived", "kitchen", day(40, 9).timestamp()).prob
        self.assertGreater(before, 0.9)
        self.assertLess(after, before * 0.7)         # the dropped habit has clearly faded (FIX-2)


class EvidenceFloor(unittest.TestCase):
    def test_not_firm_below_floor(self) -> None:
        m = PatternModel(tz="UTC")
        m.observe(ev("presence.arrived", day(1, 8)))     # a single day: a coincidence, not a fact
        exp = m.expectation("presence.arrived", "kitchen", day(1, 8).timestamp())
        self.assertLess(exp.gdays, NMIN_DAYS)
        self.assertFalse(exp.firm)

    def test_firm_once_evidence_accrues(self) -> None:
        m = PatternModel(tz="UTC")
        for d in range(1, 8):
            m.observe(ev("presence.arrived", day(d, 8)))
        exp = m.expectation("presence.arrived", "kitchen", day(7, 8).timestamp())
        self.assertGreaterEqual(exp.gdays, NMIN_DAYS)
        self.assertTrue(exp.firm)

    def test_novel_key_is_not_firm(self) -> None:
        m = PatternModel(tz="UTC")
        exp = m.expectation("presence.arrived", "attic", day(1).timestamp())
        self.assertTrue(exp.novel)
        self.assertEqual(exp.prob, 0.0)
        self.assertFalse(exp.firm)


class DeterminismAndPersistence(unittest.TestCase):
    def _run(self) -> dict:
        m = PatternModel(tz="UTC")
        for d in range(1, 13):
            m.observe(ev("presence.arrived", day(d, 8)))
            if d % 3 == 0:
                m.observe(ev("presence.arrived", day(d, 8)))   # a second same-hour fire
        return m.snapshot()

    def test_replay_is_bit_identical(self) -> None:
        self.assertEqual(self._run(), self._run())

    def test_v3_snapshot_roundtrip(self) -> None:
        snap = self._run()
        self.assertEqual(snap["version"], 3)
        m2 = PatternModel(tz="UTC")
        m2.restore(snap)
        self.assertEqual(m2.snapshot(), snap)        # exact round-trip, incl. presence + global

    def test_v2_snapshot_migrates_and_stays_bounded(self) -> None:
        # A pre-Phase-B (v2) snapshot has no presence/global. After migration, prob must still
        # be a valid probability (≤ 1), seeded best-effort and capped at the day mass.
        v2 = {
            "version": 2, "hours": 24, "half_life_days": 30.0, "tz": "UTC",
            "keys": [{
                "topic": "presence.arrived", "zone": "kitchen",
                "weights": [0.0] * 8 + [9.0] + [0.0] * 15,   # 9 events stacked at 08:00...
                "days_mass": 5.0,                            # ...over only 5 distinct days
                "last_update": day(5, 8).timestamp(), "last_obs_date": "2026-06-05",
            }],
        }
        m = PatternModel(tz="UTC")
        m.restore(v2)
        exp = m.expectation("presence.arrived", "kitchen", day(5, 8).timestamp())
        self.assertLessEqual(exp.prob, 1.0)          # the >1.0 legacy bug cannot survive migration
        self.assertEqual(m.snapshot()["version"], 3)


if __name__ == "__main__":
    unittest.main()
