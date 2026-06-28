"""GIST slices 4+5 — the day-type/daypart classifiers and the nightly fold.

Proves the honest-memory properties the owner's "slow, smart" ask rests on: a routine
promotes only on earned evidence, a STOPPED routine fades fast (counted absence —
anti-fossilization), an off-limits zone never gets a line, and the stored schema count is
bounded. All integer + deterministic (re-folding the same state yields identical bytes).

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.gist import (
    GIST_NMIN, SCALE, Beta, DayObs, Schema, confidence_q, daypart_of, daytype_of,
    encode_state, firmness, fold_day,
)


def obs(hour: int, *tokens: str) -> DayObs:
    return DayObs(minute=hour * 60, tokens=tokens)


def fold_n(days: int, observations, *, daytype="wd", off_zones=frozenset()):
    """Fold the SAME day `days` times (a stable daily routine), return the final state."""
    state: list = []
    for _ in range(days):
        state = fold_day(state, observations, daytype=daytype, off_zones=off_zones)
    return state


class ClassifierTests(unittest.TestCase):
    def test_daypart_boundaries(self) -> None:
        self.assertEqual(daypart_of(0), "night")
        self.assertEqual(daypart_of(5 * 60), "dawn")     # 300
        self.assertEqual(daypart_of(9 * 60), "am")       # 480..719
        self.assertEqual(daypart_of(13 * 60), "mid")     # 720..959
        self.assertEqual(daypart_of(17 * 60), "pm")      # 960..1139
        self.assertEqual(daypart_of(20 * 60), "eve")     # 1140..1319
        self.assertEqual(daypart_of(23 * 60), "night")   # 1320+

    def test_daypart_rejects_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            daypart_of(1440)

    def test_daytype(self) -> None:
        self.assertEqual(daytype_of("2026-06-29"), "wd")        # Monday
        self.assertEqual(daytype_of("2026-06-27"), "we")        # Saturday
        self.assertEqual(daytype_of("2026-06-29", away=True), "aw")


class FoldTests(unittest.TestCase):
    def test_a_single_fire_makes_an_obs_line(self) -> None:
        state = fold_day([], [obs(7, "coffee", "kitchen")], daytype="wd")
        self.assertEqual(len(state), 1)
        self.assertEqual(state[0].kind, "obs")          # one event = not yet a rule
        self.assertEqual(state[0].daypart, "dawn")       # 7am falls in dawn (am starts at 8)
        self.assertEqual(state[0].beta.a_q, SCALE)

    def test_sustained_routine_promotes_to_rule(self) -> None:
        state = fold_n(20, [obs(7, "coffee", "kitchen")])
        line = state[0]
        self.assertEqual(line.kind, "rule")             # earned promotion
        self.assertGreaterEqual(firmness(line.beta), GIST_NMIN)
        self.assertGreater(confidence_q(line.beta), 800)  # high confidence

    def test_stopped_routine_fades_fast_even_when_proven(self) -> None:
        # build a firm routine, then stop it while the home stays active (other daytype-wd days)
        state = fold_n(30, [obs(7, "coffee", "kitchen")])
        before = confidence_q(state[0].beta)
        self.assertGreater(before, 800)
        # now 7 wd days with NO coffee fire → counted absence floods β
        for _ in range(7):
            state = fold_day(state, [obs(19, "dinner", "kitchen")], daytype="wd")
        coffee = next(s for s in state if "coffee" in s.tokens)
        after = confidence_q(coffee.beta)
        self.assertLess(after, before - 200)            # mean-reverted within a week
        self.assertGreater(coffee.beta.b_q, 0)          # absence was counted

    def test_one_off_stays_low_confidence(self) -> None:
        state = fold_day([], [obs(3, "fridge", "kitchen")], daytype="wd")
        self.assertEqual(state[0].kind, "obs")
        self.assertLess(confidence_q(state[0].beta), 500)   # a fluke never reads as a habit

    def test_off_zone_never_gets_a_line(self) -> None:
        state = fold_day([], [obs(7, "coffee", "kitchen"), obs(8, "noise", "mum_flat")],
                         daytype="wd", off_zones=frozenset({"mum_flat"}))
        toks = {t for s in state for t in s.tokens}
        self.assertIn("kitchen", toks)
        self.assertNotIn("mum_flat", toks)              # the OFF-fence held

    def test_schema_count_is_bounded(self) -> None:
        many = [obs(h % 24, f"evt{h}", "z") for h in range(400)]
        state = fold_day([], many, daytype="wd", max_schemas=64)
        self.assertLessEqual(len(state), 64)            # hard ceiling

    def test_weekend_and_weekday_are_separate_lines(self) -> None:
        state = fold_day([], [obs(9, "run", "park")], daytype="wd")
        state = fold_day(state, [obs(9, "run", "park")], daytype="we")
        self.assertEqual(len({s.daytype for s in state}), 2)   # wd and we, not conflated

    def test_fold_is_deterministic(self) -> None:
        a = fold_n(10, [obs(7, "coffee", "kitchen"), obs(19, "dinner", "kitchen")])
        b = fold_n(10, [obs(19, "dinner", "kitchen"), obs(7, "coffee", "kitchen")])  # input reordered
        self.assertEqual(encode_state(a), encode_state(b))     # same bytes regardless of order


if __name__ == "__main__":
    unittest.main()
