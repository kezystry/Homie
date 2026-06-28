"""The Dream Journal — 'What Homie Knows', in plain words and HONESTLY.

Proves the owner's first-win surface states only firm beliefs, renders confidence as a
calibrated word (never false-precision), is honest-empty before it has learned anything, and
never leaks a raw internal event name.

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timedelta, timezone

from core import journal
from core.remember import NMIN_DAYS, PatternModel
from core.tile import Event

_BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def ev(topic: str, d: int, hour: int, zone: str | None = "kitchen") -> Event:
    ts = (_BASE + timedelta(days=d - 1, hours=hour)).timestamp()
    return Event(topic, ts, {"zone": zone}, source="test")


def when(d: int, hour: int = 12) -> float:
    return (_BASE + timedelta(days=d - 1, hours=hour)).timestamp()


class RendererTests(unittest.TestCase):
    def test_confidence_is_a_word_not_a_percent(self) -> None:
        self.assertEqual(journal.confidence_word(0.95), "almost always")
        self.assertEqual(journal.confidence_word(0.7), "usually")
        self.assertEqual(journal.confidence_word(0.45), "often")
        self.assertEqual(journal.confidence_word(0.31), "sometimes")

    def test_provenance_rounds_to_days(self) -> None:
        self.assertEqual(journal.provenance(30.4), "from 30 days")
        self.assertEqual(journal.provenance(1.0), "from 1 day")

    def test_honest_empty(self) -> None:
        lines = journal.what_homie_knows([])
        self.assertEqual(len(lines), 1)
        self.assertIn("still learning", lines[0])

    def test_sentence_is_plain_and_leaks_no_topic(self) -> None:
        row = {"topic": "presence.arrived", "zone": "kitchen", "hour": 8, "prob": 0.9, "gdays": 30.0}
        s = journal.sentence(row)
        self.assertIn("kitchen", s)
        self.assertIn("8am", s)
        self.assertIn("almost always", s)
        self.assertIn("from 30 days", s)
        self.assertNotIn("presence.arrived", s)        # never leak the internal event name

    def test_unknown_topic_falls_back_readable(self) -> None:
        row = {"topic": "widget.toggled", "zone": "den", "hour": 20, "prob": 0.5, "gdays": 10.0}
        s = journal.sentence(row)
        self.assertIn("den", s)
        self.assertNotIn("widget.toggled", s)


class BeliefsFromModelTests(unittest.TestCase):
    def test_firm_routine_becomes_a_plain_belief(self) -> None:
        m = PatternModel(tz="UTC")
        for d in range(1, 31):                          # a month of 8am kitchen presence
            m.observe(ev("presence.arrived", d, 8))
        rows = m_beliefs(m, when(30))
        self.assertTrue(rows)
        top = rows[0]
        self.assertEqual(top["topic"], "presence.arrived")
        self.assertEqual(top["hour"], 8)
        self.assertGreater(top["prob"], 0.85)
        line = journal.what_homie_knows(rows)[0]
        self.assertIn("kitchen", line)
        self.assertIn("almost always", line)

    def test_coincidence_below_floor_is_not_shown(self) -> None:
        m = PatternModel(tz="UTC")
        m.observe(ev("presence.arrived", 1, 8))         # one day only — a coincidence
        rows = m_beliefs(m, when(1))
        self.assertEqual(rows, [])                       # below NMIN_DAYS: never stated as fact
        self.assertIn("still learning", journal.what_homie_knows(rows)[0])

    def test_strongest_first(self) -> None:
        m = PatternModel(tz="UTC")
        for d in range(1, 31):
            m.observe(ev("presence.arrived", d, 8, zone="kitchen"))   # every day -> ~1.0
            if d % 2 == 0:
                m.observe(ev("presence.arrived", d, 19, zone="living"))  # half -> ~0.5
        rows = m_beliefs(m, when(30))
        self.assertGreaterEqual(len(rows), 2)
        self.assertGreaterEqual(rows[0]["prob"], rows[1]["prob"])
        self.assertEqual(rows[0]["zone"], "kitchen")


def m_beliefs(model: PatternModel, now: float):
    """Mirror Remember.beliefs() against a bare PatternModel for unit isolation."""
    rows = []
    for key in model.keys():
        b = model.belief(key, now)
        if b is None or not b["firm"] or b["prob"] < 0.3:
            continue
        topic, zone = key
        rows.append({"topic": topic, "zone": zone, **b})
    rows.sort(key=lambda r: (-r["prob"], -r["gdays"], r["topic"], r["zone"] or ""))
    return rows


if __name__ == "__main__":
    unittest.main()
