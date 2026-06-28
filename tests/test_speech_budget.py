"""Speech governance (Phase A: the muzzle before the mouths).

Proves the property the red team said was MISSING from the shipped code: a single global
cap on how often Homie talks to the owner, exempting only genuine safety/summons, deferring
overflow to the recap rather than dropping it, with an everyday owner mute on top — and all
of it replay-deterministic like the wake ledger it mirrors.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.speech_budget import (
    EXEMPT_KINDS, AdaptiveAllowance, Mute, SpeechBudget, SpeechGovernor, SpeechLedger,
    is_exempt,
)

HOUR = 3600.0
DAY = 86400.0


class ExemptionTests(unittest.TestCase):
    def test_safety_kinds_are_exempt(self) -> None:
        for k in ("safety", "alert", "emergency", "summons"):
            self.assertTrue(is_exempt(k))
        self.assertFalse(is_exempt("proactive"))
        self.assertFalse(is_exempt("delight"))

    def test_exempt_set_is_frozen(self) -> None:
        self.assertIsInstance(EXEMPT_KINDS, frozenset)


class BudgetTests(unittest.TestCase):
    def test_first_line_is_free(self) -> None:
        b = SpeechBudget()
        self.assertTrue(b.allow(0.0))  # the bucket starts full — silence is cheap, one line free

    def test_daily_ceiling_binds(self) -> None:
        # Six proactive lines/day is the owner's chosen cap. Space them an hour apart so the
        # per-hour bucket never throttles — the DAILY ceiling must still bite at the 7th.
        b = SpeechBudget(per_hour=2.0, per_day=6)
        allowed = sum(1 for h in range(24) if b.allow(h * HOUR))
        self.assertEqual(allowed, 6)

    def test_burst_is_smoothed_within_the_hour(self) -> None:
        # Capacity 2 means at most ~2 land in a tight burst; the 3rd in the same minute waits.
        b = SpeechBudget(per_hour=2.0, per_day=6)
        burst = [b.allow(0.0) for _ in range(5)]
        self.assertEqual(burst.count(True), 2)

    def test_refill_accrues_over_time(self) -> None:
        b = SpeechBudget(per_hour=2.0, per_day=6)
        self.assertTrue(b.allow(0.0))
        self.assertTrue(b.allow(0.0))          # bucket now empty (capacity 2)
        self.assertFalse(b.allow(60.0))        # a minute later: not enough accrued
        self.assertTrue(b.allow(0.0 + HOUR))   # an hour later: refilled, allowed again

    def test_day_rolls_over(self) -> None:
        b = SpeechBudget(per_hour=2.0, per_day=2)
        self.assertTrue(b.allow(0.0))
        self.assertTrue(b.allow(0.0))
        self.assertFalse(b.allow(0.0))         # daily ceiling hit
        self.assertTrue(b.allow(DAY))          # next day: fresh ceiling
        self.assertEqual(b.remaining_today(DAY), 1)

    def test_remaining_today_counts_down(self) -> None:
        b = SpeechBudget(per_hour=6.0, per_day=6)
        self.assertEqual(b.remaining_today(0.0), 6)
        b.allow(0.0)
        self.assertEqual(b.remaining_today(0.0), 5)


class MuteTests(unittest.TestCase):
    def test_mute_window(self) -> None:
        m = Mute()
        self.assertFalse(m.quiet(0.0))
        m.mute(0.0, HOUR)
        self.assertTrue(m.quiet(1800.0))      # half an hour in: still quiet
        self.assertFalse(m.quiet(HOUR + 1))   # past the window: talking again

    def test_mute_extends_never_shortens(self) -> None:
        m = Mute()
        m.mute(0.0, 2 * HOUR)
        m.mute(0.0, HOUR)                     # a shorter request must not cut the longer one
        self.assertTrue(m.quiet(90 * 60))     # still quiet at 1.5h
        m.mute(0.0, 3 * HOUR)                 # a longer request extends
        self.assertTrue(m.quiet(2.5 * HOUR))

    def test_unmute_clears(self) -> None:
        m = Mute()
        m.mute(0.0, HOUR)
        m.unmute()
        self.assertFalse(m.quiet(1.0))


class GovernorTests(unittest.TestCase):
    def test_order_exempt_beats_mute_and_budget(self) -> None:
        # A hazard must be heard even when muted and over budget.
        g = SpeechGovernor(budget=SpeechBudget(per_hour=1.0, per_day=0))
        g.mute.mute(0.0, DAY)
        d = g.decide(0.0, kind="safety", source="tile:security")
        self.assertTrue(d.spoken)
        self.assertEqual(d.outcome, "exempt")

    def test_mute_outranks_budget(self) -> None:
        g = SpeechGovernor()           # generous budget
        g.mute.mute(0.0, HOUR)
        d = g.decide(60.0, kind="proactive", source="tile:lighting")
        self.assertFalse(d.spoken)
        self.assertTrue(d.deferred)
        self.assertEqual(d.outcome, "muted")

    def test_over_budget_defers_never_drops(self) -> None:
        g = SpeechGovernor(budget=SpeechBudget(per_hour=2.0, per_day=2))
        outs = [g.decide(0.0, source=f"t{i}") for i in range(4)]
        spoken = [d for d in outs if d.spoken]
        deferred = [d for d in outs if d.deferred]
        self.assertEqual(len(spoken), 2)
        self.assertEqual(len(deferred), 2)              # overflow recorded (recap shows a lossy count)
        self.assertTrue(all(d.outcome == "budget" for d in deferred))
        # every decision is accounted for as exactly one of spoken/deferred (no silent gap)
        self.assertEqual(len(spoken) + len(deferred), 4)


class AdaptiveAllowanceTests(unittest.TestCase):
    def test_muting_shrinks_the_allowance(self) -> None:
        a = AdaptiveAllowance(start=6)
        before = a.daily()
        a.too_chatty(0.0)
        self.assertLess(a.daily(), before)          # told to be quiet → learns to talk less

    def test_repeated_mutes_keep_shrinking_to_a_floor(self) -> None:
        a = AdaptiveAllowance(start=10, lo=1)
        for _ in range(20):
            a.too_chatty(0.0)
        self.assertEqual(a.daily(), 1)              # never silences itself entirely

    def test_tolerated_days_grow_it_back(self) -> None:
        a = AdaptiveAllowance(start=6, grow=0.5)
        a.too_chatty(0.0)                            # day 0: annoyed → shrink
        low = a.value
        for d in range(1, 6):                        # five days of speaking, no annoyance
            a.note_spoke(d * DAY)
        self.assertGreater(a.value, low)            # tolerance earned back, slowly

    def test_a_quiet_day_does_not_grow_it(self) -> None:
        a = AdaptiveAllowance(start=6)
        v = a.value
        a.note_spoke(0.0)                            # day 0: spoke, no annoyance...
        # roll to day 5 WITHOUT speaking on the intervening days
        a._roll(5 * DAY)
        # only the one tolerated rollover (day 0→next) grows it once, then quiet days don't
        self.assertLessEqual(a.value, v + 0.5 + 1e-9)

    def test_bounded_above(self) -> None:
        a = AdaptiveAllowance(start=6, hi=14, grow=5)
        for d in range(1, 10):
            a.note_spoke(d * DAY)
        self.assertLessEqual(a.daily(), 14)


class GovernorLearningTests(unittest.TestCase):
    def test_governor_speaks_less_after_being_told_too_chatty(self) -> None:
        g = SpeechGovernor(budget=SpeechBudget(per_hour=20.0, per_day=6))
        # day 1: how many proactive lines get through before the learned ceiling?
        day1 = sum(1 for _ in range(20) if g.decide(0.0).spoken)
        g.note_too_chatty(0.0)                       # the owner mutes — "too chatty"
        # day 2: a fresh day, but the learned allowance is now smaller
        day2 = sum(1 for _ in range(20) if g.decide(DAY).spoken)
        self.assertLess(day2, day1)                  # it learned to talk less


class LedgerTests(unittest.TestCase):
    def test_counts_and_snapshot(self) -> None:
        g = SpeechGovernor(budget=SpeechBudget(per_hour=2.0, per_day=2))
        g.decide(0.0, kind="safety")          # exempt
        g.decide(0.0)                         # spoken
        g.decide(0.0)                         # spoken
        g.decide(0.0)                         # budget -> deferred
        snap = g.ledger.snapshot()
        self.assertEqual(snap["evaluations"], 4)
        self.assertEqual(snap["spoken"], 3)   # 1 exempt + 2 within budget
        self.assertEqual(snap["deferred"], 1)
        self.assertEqual(snap["exempt"], 1)
        self.assertEqual(snap["outcomes"]["budget"], 1)

    def test_replay_is_bit_identical(self) -> None:
        # The wake-ledger discipline: replaying the same event-time stream yields identical
        # counts, so "how chatty was I" is a falsifiable number, not a vibe.
        def run() -> dict:
            g = SpeechGovernor(budget=SpeechBudget(per_hour=2.0, per_day=4))
            for i in range(20):
                g.decide(i * 600.0, kind="proactive" if i % 3 else "safety", source=f"t{i%2}")
            return g.ledger.snapshot()
        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
