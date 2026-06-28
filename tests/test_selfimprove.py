"""Self-improvement — the nightly correction-rate trend, spoken honestly each morning.

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.selfimprove import ImproveTracker, average, note, trend
from core.tile import Event

_BASE = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def day(n: int) -> str:
    return (_BASE + timedelta(days=n)).date().isoformat()


def ts(n: int, hour: int = 12) -> float:
    return (_BASE + timedelta(days=n)).replace(hour=hour).timestamp()


class TrendTests(unittest.TestCase):
    def test_average(self) -> None:
        h = {day(0): 2, day(1): 4, day(2): 0}
        self.assertAlmostEqual(average(h), 2.0)

    def test_trend_down_is_improving(self) -> None:
        # week 1 heavy, week 2 light → improving (down)
        h = {day(i): 5 for i in range(7)}
        h.update({day(7 + i): 1 for i in range(7)})
        self.assertEqual(trend(h), "down")

    def test_trend_up(self) -> None:
        h = {day(i): 1 for i in range(7)}
        h.update({day(7 + i): 5 for i in range(7)})
        self.assertEqual(trend(h), "up")

    def test_too_little_history_is_new(self) -> None:
        self.assertEqual(trend({day(0): 1, day(1): 2}), "new")

    def test_note_is_silent_until_enough_evidence(self) -> None:
        self.assertIsNone(note({day(0): 1}, 1))

    def test_note_down_is_encouraging_and_honest(self) -> None:
        h = {day(i): 5 for i in range(7)}
        h.update({day(7 + i): 1 for i in range(7)})
        line = note(h, 1)
        self.assertIn("1 correction", line)
        self.assertIn("better", line)


class TrackerTests(unittest.IsolatedAsyncioTestCase):
    async def test_counts_corrections_and_speaks_the_morning_trend(self) -> None:
        with TemporaryDirectory() as d:
            bus = Bus()
            says: list = []
            bus.subscribe("interface.say", lambda e: says.append(e.payload["text"]))
            tr = ImproveTracker(bus, state_path=Path(d) / "improve.json", tz="UTC")
            await tr.start()
            # seed a heavy prior history straight into the file, then a light recent week
            import json
            hist = {day(i): 5 for i in range(7)}
            hist.update({day(7 + i): 1 for i in range(6)})
            (Path(d) / "improve.json").write_text(json.dumps(hist))
            tr2 = ImproveTracker(bus, state_path=Path(d) / "improve.json", tz="UTC")
            await tr2.start()
            # two corrections "yesterday" (day 13), then morning on day 14
            await bus.publish(Event("friction.correction", ts(13, 9), {"actuator": "light.kitchen"}))
            await bus.publish(Event("friction.correction", ts(13, 20), {"actuator": "light.kitchen"}))
            await bus.drain()
            await bus.publish(Event("time.morning", ts(14, 7), {"hour": 7}))
            await bus.drain()
            self.assertTrue(says)                       # it spoke a trend line
            self.assertIn("correction", says[-1])
            await tr.stop(); await tr2.stop(); await bus.aclose()

    async def test_quiet_when_no_history(self) -> None:
        bus = Bus()
        says: list = []
        bus.subscribe("interface.say", lambda e: says.append(e))
        tr = ImproveTracker(bus, tz="UTC")
        await tr.start()
        await bus.publish(Event("time.morning", ts(1, 7), {"hour": 7}))
        await bus.drain()
        self.assertEqual(says, [])                       # honest-empty: nothing to claim yet
        await tr.stop(); await bus.aclose()


if __name__ == "__main__":
    unittest.main()
