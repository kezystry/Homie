"""Remember unit tests — stdlib unittest, no external deps.

Run: python3 -m unittest discover -s tests
"""
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus
from core.remember import Remember
from core.tile import Event


def at(year: int, month: int, day: int, hour: int) -> float:
    return datetime(year, month, day, hour, 0, 0).timestamp()


def ev(topic: str, ts: float, zone: str | None = None) -> Event:
    payload = {"zone": zone} if zone is not None else {}
    return Event(topic=topic, ts=ts, payload=payload)


class RememberTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_and_expects(self) -> None:
        r = Remember()
        # presence in the kitchen at 08:00 across three distinct days
        for d in (10, 11, 12):
            await r.record(ev("presence.arrived", at(2026, 6, d, 8), "kitchen"))
        exp = await r.normal("presence.arrived", "kitchen", at(2026, 6, 13, 8))
        self.assertFalse(exp.novel)
        self.assertEqual(exp.count, 3)
        self.assertEqual(exp.days, 3)
        self.assertAlmostEqual(exp.rate, 1.0)  # ~once/day at this hour

    async def test_novel_key(self) -> None:
        r = Remember()
        await r.record(ev("presence.arrived", at(2026, 6, 10, 8), "kitchen"))
        exp = await r.normal("presence.arrived", "garage", at(2026, 6, 10, 8))
        self.assertTrue(exp.novel)
        self.assertEqual(exp.rate, 0.0)

    async def test_hour_bucketing(self) -> None:
        r = Remember()
        for d in (10, 11, 12):
            await r.record(ev("presence.arrived", at(2026, 6, d, 8), "kitchen"))
        # 03:00 is a different bucket — never seen, so count 0 (but key is known)
        exp = await r.normal("presence.arrived", "kitchen", at(2026, 6, 13, 3))
        self.assertFalse(exp.novel)
        self.assertEqual(exp.count, 0)
        self.assertEqual(exp.rate, 0.0)

    async def test_zone_separation(self) -> None:
        r = Remember()
        await r.record(ev("presence.arrived", at(2026, 6, 10, 8), "kitchen"))
        await r.record(ev("presence.arrived", at(2026, 6, 10, 8), "hallway"))
        k = await r.normal("presence.arrived", "kitchen", at(2026, 6, 11, 8))
        h = await r.normal("presence.arrived", "hallway", at(2026, 6, 11, 8))
        self.assertEqual(k.count, 1)
        self.assertEqual(h.count, 1)

    async def test_same_day_increments_count_not_days(self) -> None:
        r = Remember()
        for _ in range(4):  # four events, same day same hour
            await r.record(ev("presence.arrived", at(2026, 6, 10, 8), "kitchen"))
        exp = await r.normal("presence.arrived", "kitchen", at(2026, 6, 11, 8))
        self.assertEqual(exp.count, 4)
        self.assertEqual(exp.days, 1)
        self.assertAlmostEqual(exp.rate, 4.0)

    async def test_bootstrap_from_log(self) -> None:
        with TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            bus = Bus(log_path=path)
            for day in (10, 11, 12):
                await bus.publish(ev("presence.arrived", at(2026, 6, day, 8), "kitchen"))
            await bus.aclose()

            r = Remember()
            r.bootstrap(Bus(log_path=path))  # the log is the memory
            exp = await r.normal("presence.arrived", "kitchen", at(2026, 6, 13, 8))
            self.assertEqual(exp.count, 3)
            self.assertEqual(exp.days, 3)

    async def test_attach_records_live(self) -> None:
        bus = Bus()
        r = Remember()
        r.attach(bus)
        await bus.publish(ev("motion.detected", at(2026, 6, 10, 22), "living"))
        await bus.drain()
        exp = await r.normal("motion.detected", "living", at(2026, 6, 11, 22))
        self.assertEqual(exp.count, 1)
        await bus.aclose()


if __name__ == "__main__":
    unittest.main()
