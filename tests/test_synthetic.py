"""SyntheticPerception + scenario library — a deterministic test substrate.

Pins the M2 contract: a scenario replays bit-identically (so every downstream test
is reproducible), the privacy guard drops a forbidden event in the intake seam, and
a synthetic day drives the REAL daemon graph end to end (no camera/Pi/GPU).

Run: python3 -m unittest discover -s tests
"""
import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from core import scenarios
from core.bus import Bus
from core.daemon import DaemonConfig, build_daemon
from core.perceive import Perceive
from core.synthetic import SyntheticPerception
from core.tile import Event


class FakeHome:
    def __init__(self) -> None:
        self.driven: list = []

    async def drive(self, entity_id, command) -> None:
        self.driven.append((entity_id, command))

    def on_state_change(self, handler) -> None:
        pass


async def _published(source) -> list:
    """Drive a source through Perceive on a fresh in-memory bus; return what landed
    as (topic, ts, payload) tuples."""
    bus = Bus()
    seen: list = []
    bus.subscribe("**", lambda e: seen.append((e.topic, e.ts, dict(e.payload))))
    await Perceive(source).run(bus)
    await bus.drain()
    await bus.aclose()
    return seen


class SyntheticReplayTests(unittest.TestCase):
    def test_scenario_replays_deterministically(self) -> None:
        a = asyncio.run(_published(SyntheticPerception(scenarios.build("novel_visitor_3am"))))
        b = asyncio.run(_published(SyntheticPerception(scenarios.build("novel_visitor_3am"))))
        self.assertEqual(a, b, "a fixed scenario must replay bit-identically")
        self.assertEqual(len(a), len(scenarios.build("novel_visitor_3am")))

    def test_all_named_scenarios_build_and_are_clean(self) -> None:
        for name in scenarios.SCENARIOS:
            trace = scenarios.build(name)
            self.assertTrue(trace, f"scenario {name} should not be empty")
            published = asyncio.run(_published(SyntheticPerception(trace)))
            self.assertEqual(len(published), len(trace), f"{name}: every clean event should publish")

    def test_forbidden_event_dropped_in_intake(self) -> None:
        trace = [
            Event("presence.arrived", 1.0, {"zone": "x"}),
            Event("presence.unknown", 2.0, {"zone": "y", "faceprint": [1, 2, 3]}),  # must not cross
            Event("motion.detected", 3.0, {"zone": "z"}),
        ]
        topics = [t for (t, _, _) in asyncio.run(_published(SyntheticPerception(trace)))]
        self.assertEqual(topics, ["presence.arrived", "motion.detected"])

    def test_unknown_scenario_raises(self) -> None:
        with self.assertRaises(KeyError):
            scenarios.build("does_not_exist")


class SyntheticDrivesGraphTests(unittest.TestCase):
    def test_novel_3am_visitor_alerts_through_real_graph(self) -> None:
        async def run() -> None:
            tmp = Path(tempfile.mkdtemp(prefix="homie-synth-"))
            daemon = build_daemon(FakeHome(), None, config=DaemonConfig(state=tmp, housekeep=False))
            alerts: list = []
            try:
                await daemon.start()
                daemon.bus.subscribe("security.alert", lambda e: alerts.append(e))
                await Perceive(SyntheticPerception(scenarios.build("novel_visitor_3am"))).run(daemon.bus)
                await daemon.bus.drain()
                self.assertTrue(
                    any(a.payload.get("zone") == "back_door" for a in alerts),
                    "the synthetic 3am visitor must raise a security.alert through the real graph",
                )
            finally:
                await daemon.stop()
                shutil.rmtree(tmp, ignore_errors=True)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
