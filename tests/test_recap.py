"""The backward recap line — honest, capped, plain.

Run: python3 -m unittest discover -s tests
"""
import unittest

from core.recap import RecapFacts, compose


class RecapTests(unittest.TestCase):
    def test_full_line(self) -> None:
        line = compose(RecapFacts(
            weekday="Tuesday", presence="out 9–6",
            did=("lit the kitchen at dusk",), corrected=("the hallway light",), quiet_held=4))
        self.assertEqual(
            line,
            "Tuesday. Out 9–6. Lit the kitchen at dusk; you corrected the hallway light. "
            "Stayed quiet — 4 held.")

    def test_honest_empty_is_short(self) -> None:
        self.assertEqual(compose(RecapFacts(weekday="Sunday")), "Sunday. A quiet one.")

    def test_caps_extra_did_and_corrections(self) -> None:
        line = compose(RecapFacts(weekday="Monday",
                                  did=("lit the lamp", "closed the blinds", "warmed the hall"),
                                  corrected=("the kitchen", "the porch")))
        self.assertIn("Lit the lamp (+2 more)", line)              # sentence-start capitalized
        self.assertIn("you corrected the kitchen (+1 more)", line)

    def test_presence_only(self) -> None:
        self.assertEqual(compose(RecapFacts(weekday="Friday", presence="home most of the day")),
                         "Friday. Home most of the day.")

    def test_quiet_count_suppresses_quiet_one(self) -> None:
        # When there IS a relief count, don't also append the honest-empty "A quiet one."
        line = compose(RecapFacts(weekday="Wednesday", quiet_held=2))
        self.assertIn("2 held", line)
        self.assertNotIn("A quiet one", line)


if __name__ == "__main__":
    unittest.main()
