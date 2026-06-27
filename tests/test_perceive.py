"""Perception privacy-guard tests — raw imagery can never leave the edge.

`assert_emittable` is the fail-closed guard the perception adapter calls before
every emit, mirroring the mesh PrivacyGuard one layer earlier (at the source).

Run: python3 -m unittest discover -s tests
"""
import asyncio
import unittest

from core.bus import Bus
from core.mesh import PrivacyGuard
from core.perceive import FORBIDDEN, Perceive, PrivacyViolation, assert_emittable
from core.synthetic import SyntheticPerception
from core.tile import Event


class AssertEmittableTests(unittest.TestCase):
    def test_clean_event_passes(self) -> None:
        assert_emittable("presence.arrived", {"zone": "entry", "label": "alice"})  # no raise

    def test_forbidden_topic_segment_rejected(self) -> None:
        for topic in ("camera.frame", "face.faceprint.ready", "image.raw"):
            with self.assertRaises(PrivacyViolation):
                assert_emittable(topic, {"zone": "entry"})

    def test_forbidden_payload_key_rejected(self) -> None:
        for key in ("frame", "crop", "vector", "faceprint", "image", "raw"):
            with self.assertRaises(PrivacyViolation):
                assert_emittable("presence.unknown", {"zone": "entry", key: "..."})

    def test_blob_sized_payload_rejected(self) -> None:
        with self.assertRaises(PrivacyViolation):
            assert_emittable("presence.arrived", {"zone": "x", "blob": "A" * 5000})

    def test_shares_forbidden_set_with_mesh_guard(self) -> None:
        # single source of truth — the two guards can never drift apart
        self.assertIs(FORBIDDEN, PrivacyGuard.FORBIDDEN)


class _FakeLiveSource:
    """A second PerceptionSource (stands in for the live mesh/device adapter) so we
    can prove Perceive.run is source-agnostic — the one intake path."""

    def __init__(self, events: list) -> None:
        self._events = events

    async def events(self):
        for e in self._events:
            yield e


async def _run_through_perceive(source) -> list:
    bus = Bus()
    seen: list = []
    bus.subscribe("**", lambda e: seen.append(e.topic))
    await Perceive(source).run(bus)
    await bus.drain()
    await bus.aclose()
    return seen


class PerceiveIntakeSeamTests(unittest.TestCase):
    def test_run_is_the_intake_seam(self) -> None:
        # both the synthetic harness and a fake live adapter flow through the SAME
        # Perceive.run, and both are guarded identically.
        events = [
            Event("presence.arrived", 1.0, {"zone": "a"}),
            Event("presence.unknown", 2.0, {"zone": "b", "faceprint": [0, 1]}),  # dropped by the guard
            Event("motion.detected", 3.0, {"zone": "c"}),
        ]
        for source in (SyntheticPerception(events), _FakeLiveSource(events)):
            topics = asyncio.run(_run_through_perceive(source))
            self.assertEqual(topics, ["presence.arrived", "motion.detected"])

    def test_intake_stamps_source(self) -> None:
        seen: list = []

        async def go() -> None:
            bus = Bus()
            bus.subscribe("presence.**", lambda e: seen.append(e.source))
            await Perceive(SyntheticPerception([Event("presence.arrived", 1.0, {"zone": "a"})])).run(bus)
            await bus.drain()
            await bus.aclose()

        asyncio.run(go())
        self.assertEqual(seen, ["perception"])  # the intake seam stamps origin


if __name__ == "__main__":
    unittest.main()
