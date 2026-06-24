"""Bus unit tests — stdlib unittest, no external deps.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from core.bus import Bus, DurabilityLog, Priority, Request
from core.tile import Event


def ev(topic: str, **payload) -> Event:
    return Event(topic=topic, ts=0.0, payload=payload)


class BusDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bus = Bus()

    async def asyncTearDown(self) -> None:
        await self.bus.aclose()

    async def test_pubsub_delivery(self) -> None:
        got = []
        self.bus.subscribe("presence.arrived", lambda e: got.append(e) or _noop())
        await self.bus.publish(ev("presence.arrived", who="han"))
        await self.bus.drain()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].payload["who"], "han")

    async def test_glob_one_segment(self) -> None:
        got = []
        self.bus.subscribe("presence.*", _collect(got))
        await self.bus.publish(ev("presence.arrived"))
        await self.bus.publish(ev("presence.kitchen.arrived"))  # 2 segments — no match
        await self.bus.publish(ev("presence"))  # bare — no match
        await self.bus.drain()
        self.assertEqual([e.topic for e in got], ["presence.arrived"])

    async def test_glob_multi_segment(self) -> None:
        got = []
        self.bus.subscribe("sensor.**", _collect(got))
        await self.bus.publish(ev("sensor.temp"))
        await self.bus.publish(ev("sensor.kitchen.temp"))
        await self.bus.publish(ev("sensorx.temp"))  # no match
        await self.bus.drain()
        self.assertEqual({e.topic for e in got}, {"sensor.temp", "sensor.kitchen.temp"})

    async def test_no_cross_delivery(self) -> None:
        a, b = [], []
        self.bus.subscribe("a.x", _collect(a))
        self.bus.subscribe("b.x", _collect(b))
        await self.bus.publish(ev("a.x"))
        await self.bus.drain()
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 0)

    async def test_fault_isolation(self) -> None:
        good = []

        async def boom(_e):
            raise RuntimeError("nope")

        bad_sub = self.bus.subscribe("t.x", boom)
        self.bus.subscribe("t.x", _collect(good))
        await self.bus.publish(ev("t.x"))
        await self.bus.publish(ev("t.x"))
        await self.bus.drain()
        self.assertEqual(len(good), 2)  # sibling unaffected
        self.assertEqual(bad_sub.faults, 2)  # failure contained + counted

    async def test_backpressure_drop_oldest(self) -> None:
        gate = asyncio.Event()
        seen = []

        async def slow(e):
            await gate.wait()
            seen.append(e)

        sub = Bus(maxsize=2)
        s = sub.subscribe("q.x", slow)
        for i in range(5):
            await sub.publish(ev("q.x", n=i))
        self.assertEqual(s.dropped, 3)  # kept newest 2
        gate.set()
        await sub.drain()
        self.assertEqual([e.payload["n"] for e in seen], [3, 4])
        await sub.aclose()


class ArbitrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_priority_wins(self) -> None:
        bus = Bus()
        reqs = [
            Request("light.k", True, Priority.CONVENIENCE, "kitchen", at=1.0),
            Request("light.k", False, Priority.SAFETY, "security", at=0.0),
        ]
        winner = await bus.arbitrate("light.k", reqs)
        self.assertEqual(winner.tile, "security")

    async def test_recency_tiebreak(self) -> None:
        bus = Bus()
        reqs = [
            Request("light.k", 1, Priority.AUTOMATION, "a", at=1.0),
            Request("light.k", 2, Priority.AUTOMATION, "b", at=2.0),
        ]
        winner = await bus.arbitrate("light.k", reqs)
        self.assertEqual(winner.tile, "b")

    async def test_empty_returns_none(self) -> None:
        bus = Bus()
        self.assertIsNone(await bus.arbitrate("light.k", []))


class DurabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_append_and_replay(self) -> None:
        with TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            bus = Bus(log_path=path)
            for i in range(3):
                await bus.publish(ev("e.x", n=i))
            await bus.aclose()
            replayed = list(DurabilityLog(path).replay())
            self.assertEqual([e.payload["n"] for e in replayed], [0, 1, 2])
            self.assertEqual([e.topic for e in replayed], ["e.x"] * 3)

    async def test_no_log_is_noop(self) -> None:
        bus = Bus(log_path=None)
        await bus.publish(ev("e.x"))
        self.assertEqual(list(bus.replay()), [])
        await bus.aclose()


def _noop():
    async def _():
        return None

    return _()


def _collect(sink: list):
    async def handler(e: Event) -> None:
        sink.append(e)

    return handler


if __name__ == "__main__":
    unittest.main()
