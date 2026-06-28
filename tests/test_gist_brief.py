"""GIST slice 6 — the prose BRIEF: honest, plain-words "What Homie Knows".

Proves the council's honesty contract: present tense ONLY for a live belief, "starting to
notice" below the evidence floor, PAST tense the instant confidence falls below the action
threshold. A faded line can never read as a present claim.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.gist import (
    DayObs, conf_word, fold_day, line_text, render_brief,
)


def obs(hour: int, *tokens: str) -> DayObs:
    return DayObs(minute=hour * 60, tokens=tokens)


def fold_n(days: int, observations, *, daytype="wd"):
    state: list = []
    for _ in range(days):
        state = fold_day(state, observations, daytype=daytype)
    return state


class ConfWordTests(unittest.TestCase):
    def test_total_and_monotone(self) -> None:
        self.assertEqual(conf_word(950), "almost always")
        self.assertEqual(conf_word(700), "usually")
        self.assertEqual(conf_word(450), "often")
        self.assertEqual(conf_word(100), "sometimes")
        self.assertEqual(conf_word(0), "sometimes")     # total — defined everywhere


class BriefTests(unittest.TestCase):
    def test_live_belief_is_present_tense(self) -> None:
        state = fold_n(30, [obs(9, "coffee", "kitchen")])
        text = line_text(state[0])
        self.assertIn("you", text.lower())
        self.assertIn("coffee in the kitchen", text)
        self.assertNotIn("used to", text)               # a live belief is never past tense
        self.assertNotIn("starting to notice", text)

    def test_coincidence_is_tentative(self) -> None:
        state = fold_day([], [obs(3, "fridge", "kitchen")], daytype="wd")
        self.assertIn("starting to notice", line_text(state[0]))   # below the floor → hedged

    def test_faded_proven_line_is_past_tense(self) -> None:
        state = fold_n(40, [obs(7, "run", "park")])     # firmly proven
        for _ in range(25):                              # then genuinely stopped (active no-show)
            state = fold_day(state, [obs(19, "dinner", "kitchen")], daytype="wd")
        run = next(s for s in state if "run" in s.tokens)
        text = line_text(run)
        self.assertTrue(text.startswith("You used to"))  # faded → honest past tense, never present

    def test_render_brief_orders_and_filters(self) -> None:
        state = fold_n(20, [obs(7, "coffee", "kitchen"), obs(19, "dinner", "kitchen")])
        lines = render_brief(state)
        self.assertTrue(lines)
        self.assertTrue(all(isinstance(x, str) for x in lines))
        # hiding the tentative tier yields only firm lines
        firm_only = render_brief(state, min_firmness=3)
        self.assertTrue(all("starting to notice" not in x for x in firm_only))

    def test_no_off_limits_token_can_appear(self) -> None:
        # the fold OFF-fences; the brief therefore never sees an off-limits token
        state = fold_day([], [obs(9, "noise", "mum_flat")], daytype="wd",
                         off_zones=frozenset({"mum_flat"}))
        self.assertEqual(render_brief(state), [])


if __name__ == "__main__":
    unittest.main()
