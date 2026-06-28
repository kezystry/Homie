"""Pattern-decay tests for PatternModel — the model forgets, gracefully.

Run: python3 -m unittest discover -s tests
"""
import json
import unittest
from datetime import date, datetime, timedelta, timezone

from core.remember import EPS, HALF_LIFE_DAYS, PatternModel
from core.tile import Event

DAY = 86400.0
HL = HALF_LIFE_DAYS * DAY  # one half-life in seconds


def day_at(i: int, hour: int = 8) -> float:
    """Epoch ts for hour:00 on day i (calendar days from 2026-01-01)."""
    d = date(2026, 1, 1) + timedelta(days=i)
    return datetime(d.year, d.month, d.day, hour, 0, 0).timestamp()


def ev(topic: str, ts: float, zone: str | None = "kitchen") -> Event:
    return Event(topic=topic, ts=ts, payload={"zone": zone})


class DecayTests(unittest.TestCase):
    def test_decay_halves_mass_at_one_half_life(self) -> None:
        m = PatternModel()
        t = day_at(0)
        m.observe(ev("presence.arrived", t))
        m.decay(t + HL)  # exactly one half-life later, no new observation
        e = m.expectation("presence.arrived", "kitchen", t + HL)
        self.assertAlmostEqual(e.count, 0.5, places=6)  # mass halved
        self.assertAlmostEqual(e.days, 0.5, places=6)
        self.assertAlmostEqual(e.rate, 1.0, places=6)  # but the rate holds
        self.assertFalse(e.novel)

    def test_silent_key_eventually_goes_novel(self) -> None:
        m = PatternModel()
        t = day_at(0)
        m.observe(ev("presence.arrived", t))
        m.decay(t + 10 * HL)  # 2^-10 ≈ 9.8e-4 < EPS → pruned
        self.assertTrue(m.expectation("presence.arrived", "kitchen", t + 10 * HL).novel)

    def test_not_novel_just_inside_epsilon(self) -> None:
        m = PatternModel()
        t = day_at(0)
        m.observe(ev("presence.arrived", t))
        m.decay(t + 9 * HL)  # 2^-9 ≈ 1.95e-3 > EPS → survives
        self.assertFalse(m.expectation("presence.arrived", "kitchen", t + 9 * HL).novel)

    def test_steady_pattern_holds_stable_rate(self) -> None:
        m = PatternModel()
        for i in range(150):  # ~5 half-lives of once-a-day at 08:00
            m.observe(ev("presence.arrived", day_at(i)))
        e = m.expectation("presence.arrived", "kitchen", day_at(150))
        self.assertAlmostEqual(e.rate, 1.0, places=2)  # ~1/day
        self.assertGreater(e.days, 40)  # denominator saturates near 1/(1-2^(-1/30)) ≈ 43.8

    def test_changed_routine_adapts(self) -> None:
        # 60 days at hour 8, then 60 days at hour 20 → hour 20 should dominate
        m = PatternModel()
        for i in range(60):
            m.observe(ev("presence.arrived", day_at(i, 8)))
        for i in range(60, 120):
            m.observe(ev("presence.arrived", day_at(i, 20)))
        now = day_at(120)
        r8 = m.expectation("presence.arrived", "kitchen", now).count  # via hour-8 query
        e8 = m.expectation("presence.arrived", "kitchen", day_at(120, 8))
        e20 = m.expectation("presence.arrived", "kitchen", day_at(120, 20))
        self.assertGreater(e20.count, e8.count)  # the old 8am habit has faded under the new one

    def test_snapshot_roundtrip_preserves_decay_state(self) -> None:
        m = PatternModel()
        for i in range(5):
            m.observe(ev("presence.arrived", day_at(i)))
        snap = json.loads(json.dumps(m.snapshot()))  # JSON-safe
        m2 = PatternModel()
        m2.restore(snap)
        now = day_at(40)
        a = m.expectation("presence.arrived", "kitchen", now)
        b = m2.expectation("presence.arrived", "kitchen", now)
        self.assertAlmostEqual(a.rate, b.rate, places=9)
        self.assertAlmostEqual(a.count, b.count, places=5)
        self.assertEqual(a.novel, b.novel)
        self.assertEqual(m2.snapshot()["version"], 3)

    def test_decay_idempotent_at_fixed_now(self) -> None:
        m = PatternModel()
        m.observe(ev("presence.arrived", day_at(0)))
        m.decay(day_at(5))
        once = json.dumps(m.snapshot())
        m.decay(day_at(5))  # same now → must not double-decay
        self.assertEqual(json.dumps(m.snapshot()), once)

    def test_out_of_order_event_does_not_move_clock_back(self) -> None:
        m = PatternModel()
        t = day_at(10)
        m.observe(ev("presence.arrived", t))
        m.observe(ev("presence.arrived", t - 5 * DAY))  # an older event arrives late
        key = ("presence.arrived", "kitchen")
        self.assertEqual(m._last[key], t)  # clock held; not rewound
        self.assertTrue(all(x >= 0.0 for x in m._w[key]))  # finite, non-negative

    def test_v1_snapshot_migrates_forward(self) -> None:
        counts = [0] * 24
        counts[8] = 5
        v1 = {
            "version": 1,
            "hours": 24,
            "keys": [{"topic": "presence.arrived", "zone": "kitchen",
                      "counts": counts, "dates": ["2026-01-01", "2026-01-02", "2026-01-03"]}],
        }
        m = PatternModel()
        m.restore(v1)
        # at the migrated last-observed instant (hour 8), rate == old counts[8] / len(dates)
        e = m.expectation("presence.arrived", "kitchen", day_at(2, 8))  # 2026-01-03 08:00
        self.assertFalse(e.novel)
        self.assertAlmostEqual(e.rate, 5 / 3, places=3)
        self.assertEqual(m.snapshot()["version"], 3)

    def test_unknown_future_version_rejected(self) -> None:
        m = PatternModel()
        with self.assertRaises(ValueError):
            m.restore({"version": 99, "keys": []})

    def test_pinned_timezone_buckets_by_zone(self) -> None:
        # an event at 12:00 UTC lands in the hour-12 bucket of a UTC-pinned model
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        m = PatternModel(tz="UTC")
        m.observe(ev("presence.arrived", ts))
        q12 = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc).timestamp()  # next day, hour 12 UTC
        q13 = datetime(2026, 1, 2, 13, 0, 0, tzinfo=timezone.utc).timestamp()
        self.assertGreater(m.expectation("presence.arrived", "kitchen", q12).count, 0.0)
        self.assertEqual(m.expectation("presence.arrived", "kitchen", q13).count, 0.0)  # different bucket
        self.assertEqual(m.snapshot()["tz"], "UTC")  # tz recorded for portable restore


if __name__ == "__main__":
    unittest.main()
