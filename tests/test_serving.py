"""Serving discipline (M6) — the latency SLO and warm/cold policy.

Both are pure, so the brain's "is it quick?" and "should the GPU stay warm?" logic is
exercised with no model and no clock-of-the-wall (an injected clock keeps it deterministic).

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.serving import LatencySLO, RejectionRate, WarmPolicy


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


class LatencySLOTests(unittest.TestCase):
    def test_met_and_breach(self):
        slo = LatencySLO(budget_ms=100.0)
        self.assertTrue(slo.record(50.0))
        self.assertFalse(slo.record(200.0))
        self.assertEqual(slo.breaches, 1)
        self.assertEqual(slo.total, 2)
        self.assertAlmostEqual(slo.breach_rate(), 0.5)

    def test_quantiles(self):
        slo = LatencySLO(budget_ms=4000.0)
        for ms in range(1, 11):  # 1..10 ms
            slo.record(float(ms))
        self.assertEqual(slo.p50(), 5.0)   # nearest-rank median of 1..10
        self.assertEqual(slo.p95(), 10.0)
        self.assertEqual(slo.breach_rate(), 0.0)

    def test_empty_quantiles_are_none(self):
        slo = LatencySLO()
        self.assertIsNone(slo.p50())
        self.assertIsNone(slo.p95())

    def test_window_bounds_samples(self):
        slo = LatencySLO(window=5)
        for ms in range(20):
            slo.record(float(ms))
        self.assertEqual(slo.summary()["samples"], 5)
        self.assertEqual(slo.total, 20)

    def test_summary_is_json_safe(self):
        slo = LatencySLO(budget_ms=100.0)
        slo.record(50.0)
        s = slo.summary()
        self.assertEqual(s["budget_ms"], 100.0)
        self.assertEqual(s["p50_ms"], 50.0)


class WarmPolicyTests(unittest.TestCase):
    def test_cold_until_first_wake(self):
        clk = Clock(0.0)
        warm = WarmPolicy(keep_warm_s=300.0, now=clk)
        self.assertFalse(warm.is_warm())

    def test_warm_within_window_cold_after(self):
        clk = Clock(0.0)
        warm = WarmPolicy(keep_warm_s=300.0, now=clk)
        warm.note_wake()           # wake at t=0
        clk.t = 100.0
        self.assertTrue(warm.is_warm())
        clk.t = 400.0
        self.assertFalse(warm.is_warm())

    def test_close_wakes_widen_window(self):
        clk = Clock(0.0)
        warm = WarmPolicy(keep_warm_s=300.0, now=clk)
        warm.note_wake()           # t=0
        clk.t = 100.0
        warm.note_wake()           # gap 100 <= 300 -> window 300*1.5 = 450
        self.assertEqual(warm.warm_window_s(), 450.0)
        clk.t = 540.0              # 540 - 100 = 440 <= 450 -> still warm
        self.assertTrue(warm.is_warm())

    def test_sparse_wake_relaxes_window(self):
        clk = Clock(0.0)
        warm = WarmPolicy(keep_warm_s=300.0, now=clk)
        warm.note_wake()           # t=0
        clk.t = 100.0
        warm.note_wake()           # window -> 450
        clk.t = 2000.0
        warm.note_wake()           # gap 1900 > 300 -> back to 300
        self.assertEqual(warm.warm_window_s(), 300.0)

    def test_window_capped(self):
        clk = Clock(0.0)
        warm = WarmPolicy(keep_warm_s=300.0, max_warm_s=600.0, now=clk)
        for _ in range(10):        # repeated close wakes would blow past max without the cap
            warm.note_wake()
        self.assertLessEqual(warm.warm_window_s(), 600.0)


class RejectionRateTests(unittest.TestCase):
    def test_rate_is_fraction_over_the_window(self) -> None:
        r = RejectionRate(window=4)
        self.assertEqual(r.rate(), 0.0)               # honest-empty
        for rej in (True, False, False, False):
            r.record(rej)
        self.assertAlmostEqual(r.rate(), 0.25)        # 1 of 4
        self.assertEqual(r.summary()["rejections"], 1)

    def test_window_rolls(self) -> None:
        r = RejectionRate(window=2)
        r.record(True); r.record(True)
        self.assertEqual(r.rate(), 1.0)
        r.record(False); r.record(False)              # oldest two drop out
        self.assertEqual(r.rate(), 0.0)
        self.assertEqual(r.attempts, 4)               # lifetime total is unbounded


if __name__ == "__main__":
    unittest.main()
