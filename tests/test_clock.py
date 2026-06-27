"""Clock — the heartbeat + timer seam (fixes second-review N1).

Pins the structural fix: a timer set on the bus fires later even when NOTHING else
happens (the empty-room auto-off that today never fires), timers rearm/cancel, and
the tick loop emits tick.minute / tick.hour.

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest

from core.bus import Bus
from core.clock import Clock
from core.daemon import DaemonConfig, build_daemon
from core.tile import Event


class FakeHome:
    def __init__(self) -> None:
        self.driven: list = []

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        pass


class TimerSeamTests(unittest.TestCase):
    def test_timer_fires_in_empty_room(self) -> None:
        """The N1 bug: with NO further events, a set timer still fires."""
        async def run() -> None:
            bus = Bus()
            fired: list = []
            topics: list = []
            bus.subscribe("timer.fired", lambda e: fired.append(e.payload))
            bus.subscribe("**", lambda e: topics.append(e.topic))
            clock = Clock(bus, tick_seconds=10_000)  # ticks won't fire during the test
            await clock.start()
            await bus.publish(Event("timer.set", 0.0, {"after": 0.02, "key": "lighting.off.living"}))
            await bus.drain()
            await asyncio.sleep(0.05)  # the ONLY thing that happens — no zone events
            await bus.drain()
            await clock.stop()
            await bus.aclose()
            self.assertEqual(fired, [{"key": "lighting.off.living", "data": None}])
            # nothing but the timer machinery happened — no presence/motion/tick
            self.assertEqual(set(topics), {"timer.set", "timer.fired"})

        asyncio.run(run())

    def test_rearm_replaces_pending_timer(self) -> None:
        async def run() -> None:
            bus = Bus()
            fired: list = []
            bus.subscribe("timer.fired", lambda e: fired.append(e.payload.get("data")))
            clock = Clock(bus, tick_seconds=10_000)
            await clock.start()
            await bus.publish(Event("timer.set", 0.0, {"after": 0.2, "key": "k", "data": "first"}))
            await bus.drain()
            await bus.publish(Event("timer.set", 0.0, {"after": 0.02, "key": "k", "data": "second"}))
            await bus.drain()
            await asyncio.sleep(0.1)
            await bus.drain()
            await clock.stop()
            await bus.aclose()
            self.assertEqual(fired, ["second"])  # the rearm replaced the first; it never fired

        asyncio.run(run())

    def test_cancel_drops_pending_timer(self) -> None:
        async def run() -> None:
            bus = Bus()
            fired: list = []
            bus.subscribe("timer.fired", lambda e: fired.append(e.payload.get("key")))
            clock = Clock(bus, tick_seconds=10_000)
            await clock.start()
            await bus.publish(Event("timer.set", 0.0, {"after": 0.05, "key": "k"}))
            await bus.drain()
            await bus.publish(Event("timer.cancel", 0.0, {"key": "k"}))  # re-occupancy cancels auto-off
            await bus.drain()
            await asyncio.sleep(0.1)
            await bus.drain()
            await clock.stop()
            await bus.aclose()
            self.assertEqual(fired, [])  # the cancelled timer never fired

        asyncio.run(run())

    def test_malformed_timer_set_ignored(self) -> None:
        async def run() -> None:
            bus = Bus()
            fired: list = []
            bus.subscribe("timer.fired", lambda e: fired.append(e))
            clock = Clock(bus, tick_seconds=10_000)
            await clock.start()
            for bad in ({"key": "k"}, {"after": -1, "key": "k"}, {"after": 0.0}, {"after": True, "key": "k"}):
                await bus.publish(Event("timer.set", 0.0, bad))
            await bus.drain()
            await asyncio.sleep(0.02)
            await bus.drain()
            await clock.stop()
            await bus.aclose()
            self.assertEqual(fired, [])

        asyncio.run(run())


class TickTests(unittest.TestCase):
    def test_tick_minute_and_hour(self) -> None:
        async def run() -> None:
            bus = Bus()
            ticks: list = []
            bus.subscribe("tick.**", lambda e: ticks.append(e.topic))

            calls = {"n": 0}

            async def fake_sleep(_s: float) -> None:
                calls["n"] += 1
                if calls["n"] > 3:  # after three ticks, park forever
                    await asyncio.Event().wait()

            clock = Clock(bus, sleep=fake_sleep, now=lambda: 1000.0)  # fixed now -> one hour boundary
            await clock.start()
            for _ in range(20):  # let the tick task run its iterations
                await asyncio.sleep(0)
            await bus.drain()
            await clock.stop()
            await bus.aclose()
            self.assertEqual(ticks.count("tick.minute"), 3)
            self.assertEqual(ticks.count("tick.hour"), 1)  # only the first crosses an hour boundary

        asyncio.run(run())


class ClockInDaemonTests(unittest.TestCase):
    def test_timer_works_through_the_daemon(self) -> None:
        async def run() -> None:
            daemon = build_daemon(FakeHome(), None, config=DaemonConfig(housekeep=False))
            fired: list = []
            try:
                await daemon.start()
                daemon.bus.subscribe("timer.fired", lambda e: fired.append(e.payload.get("key")))
                await daemon.bus.publish(Event("timer.set", 0.0, {"after": 0.02, "key": "demo"}))
                await daemon.bus.drain()
                await asyncio.sleep(0.05)
                await daemon.bus.drain()
                self.assertEqual(fired, ["demo"])
            finally:
                await daemon.stop()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
